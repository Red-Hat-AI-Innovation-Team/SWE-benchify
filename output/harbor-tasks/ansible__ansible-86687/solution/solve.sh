#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/multipart-generator.yaml b/changelogs/fragments/multipart-generator.yaml
new file mode 100644
index 00000000000000..134ec9c2d14c82
--- /dev/null
+++ b/changelogs/fragments/multipart-generator.yaml
@@ -0,0 +1,4 @@
+minor_changes:
+- url `multipart/form-data` - Replace Python ``email`` multipart generator with custom generator, allowing for binary content without ``Content-Transfer-Encoding``
+bugfixes:
+- uri - Enable multipart/form-data requests over 2GB (https://github.com/ansible/ansible/issues/76666)
diff --git a/lib/ansible/module_utils/urls.py b/lib/ansible/module_utils/urls.py
index a1e36a6c5ce0e0..ee00c50a5113f2 100644
--- a/lib/ansible/module_utils/urls.py
+++ b/lib/ansible/module_utils/urls.py
@@ -30,14 +30,10 @@
 from __future__ import annotations
 
 import base64
-import email.encoders
-import email.mime.application
-import email.mime.multipart
-import email.mime.nonmultipart
-import email.parser
-import email.policy
-import email.utils
+import binascii
+import collections.abc as _c
 import http.client
+import io
 import mimetypes
 import netrc
 import os
@@ -50,6 +46,7 @@
 import urllib.error
 import urllib.request
 from contextlib import contextmanager
+from functools import partial
 from http import cookiejar
 from urllib.parse import unquote, urlparse, urlunparse
 from urllib.request import BaseHandler
@@ -68,6 +65,7 @@
 from ansible.module_utils.basic import missing_required_lib
 from ansible.module_utils.common.collections import Mapping, is_sequence
 from ansible.module_utils.common.text.converters import to_bytes, to_native, to_text
+from ansible.module_utils.compat import typing as _t
 
 try:
     import ssl
@@ -1005,31 +1003,237 @@ def open_url(url, data=None, headers=None, method=None, use_proxy=True,
                           unredirected_headers=unredirected_headers, decompress=decompress, ciphers=ciphers, use_netrc=use_netrc)
 
 
-def prepare_multipart(fields):
-    """Takes a mapping, and prepares a multipart/form-data body
+# deprecated: description='TypedDict Required/NotRequired' python_version='3.11'
+# TODO: When Python 3.11+ is the minimum, use Required/NotRequired to properly
+# enforce that at least one of filename or content is required
+class _MultipartField(_t.TypedDict, total=False):
+    """TypedDict for multipart field configuration.
 
-    :arg fields: Mapping
-    :returns: tuple of (content_type, body) where ``content_type`` is
-        the ``multipart/form-data`` ``Content-Type`` header including
-        ``boundary`` and ``body`` is the prepared bytestring body
+    At least one of 'filename' or 'content' must be provided.
+    """
+    filename: str
+    content: str
+    mime_type: str
+    multipart_encoding: _t.Literal['base64', '7or8bit']
 
-    Payload content from a file will be base64 encoded and will include
-    the appropriate ``Content-Transfer-Encoding`` and ``Content-Type``
-    headers.
 
-    Example:
-        {
-            "file1": {
-                "filename": "/bin/true",
-                "mime_type": "application/octet-stream"
-            },
-            "file2": {
-                "content": "text based file content",
-                "filename": "fake.txt",
-                "mime_type": "text/plain",
-            },
-            "text_form_field": "value"
-        }
+_CTE: _t.TypeAlias = _t.Literal[b'base64', b'7bit']
+_EncToCTEMap: dict[str, _CTE] = {
+    'base64': b'base64',
+    '7or8bit': b'7bit',
+}
+
+# Constants for multipart generation
+_CHUNK_SIZE = 65536
+_DEFAULT_MIME_TYPE = b'application/octet-stream'
+_TEXT_CONTENT_TYPE = b'text/plain'
+
+
+class _MultipartReader(io.RawIOBase):
+    """File-like reader for streaming multipart content without materializing in memory.
+
+    Wraps a generator that yields multipart chunks and provides read()/readinto()
+    interface compatible with urllib and other file-like consumers.
+    """
+
+    def __init__(self, generator: _t.Generator[bytes, None, None]) -> None:
+        self._generator = generator
+        self._buffer = bytearray()
+        self._exhausted = False
+
+    def readable(self) -> bool:
+        return True
+
+    def readinto(self, buffer: bytearray | memoryview) -> int:  # type: ignore[override]
+        """Read up to len(buffer) bytes into buffer. Returns number of bytes read."""
+        size = len(buffer)
+        data = self.read(size)
+        n = len(data)
+        buffer[:n] = data
+        return n
+
+    def read(self, size: int = -1) -> bytes:
+        """Read up to size bytes. If size is -1 or None, read all remaining data."""
+        if self._exhausted and not self._buffer:
+            return b''
+
+        if size is None or size < 0:
+            all_data = bytearray(self._buffer)
+            if not self._exhausted:
+                for chunk in self._generator:
+                    all_data.extend(chunk)
+                self._exhausted = True
+            self._buffer.clear()
+            return bytes(all_data)
+
+        while len(self._buffer) < size and not self._exhausted:
+            try:
+                chunk = next(self._generator)
+                self._buffer.extend(chunk)
+            except StopIteration:
+                self._exhausted = True
+                break
+
+        data = bytes(self._buffer[:size])
+        del self._buffer[:size]
+        return data
+
+
+class MultipartProtocol(_t.Protocol):
+    """Protocol for multipart form-data generators.
+
+    This defines the public interface for multipart objects without
+    exposing implementation details. Use this for type hints.
+    """
+
+    @property
+    def content_type(self) -> str:
+        """Content-Type header value including boundary."""
+
+    def add(
+        self,
+        name: bytes,
+        filename: bytes | None = None,
+        filepath: bytes | None = None,
+        content: bytes | None = None,
+        cte: _CTE | None = None,
+        ct: bytes = _DEFAULT_MIME_TYPE,
+    ) -> None:
+        """Add a field to the multipart body."""
+
+    def as_iter(self) -> _t.Generator[bytes, None, None]:
+        """Generator yielding each multipart part as bytes, then the final boundary."""
+
+    def as_fp(self) -> _MultipartReader:
+        """Return a file-like reader that streams multipart content."""
+
+    def as_bytes(self) -> bytes:
+        """Return all multipart content as bytes."""
+
+
+class _Multipart:
+    class _Part(_t.TypedDict):
+        name: bytes
+        filename: bytes | None
+        filepath: bytes | None
+        content: bytes | None
+        cte: _CTE | None
+        ct: bytes
+
+    def __init__(self) -> None:
+        self._nl = b'\r\n'
+        self._boundary = b'----AnsibleFormBoundary' + binascii.hexlify(os.urandom(16))
+        self._parts: list[_Multipart._Part] = []
+
+    @property
+    def content_type(self) -> str:
+        return 'multipart/form-data; boundary=%s' % self._boundary.decode()
+
+    def add(
+        self,
+        name: bytes,
+        filename: bytes | None = None,
+        filepath: bytes | None = None,
+        content: bytes | None = None,
+        cte: _CTE | None = None,
+        ct: bytes = _DEFAULT_MIME_TYPE,
+    ) -> None:
+        # deprecated: description='TypedDict Required/NotRequired for _MultipartField' python_version='3.11'
+        if filepath and content:
+            raise ValueError('only one of filepath or content can be supplied')
+        if not filepath and not content:
+            raise ValueError('one of filepath or content must be supplied')
+        self._parts.append({
+            'name': name,
+            'filename': filename,
+            'filepath': filepath,
+            'content': content,
+            'cte': cte,
+            'ct': ct,
+        })
+
+    def as_iter(self) -> _t.Generator[bytes, None, None]:
+        """Generator yielding each multipart part as bytes, then the final boundary."""
+        for part in self._parts:
+            yield self._generate_header(part)
+
+            if part['cte']:
+                if part['filepath']:
+                    with open(part['filepath'], 'rb') as f:
+                        yield from self._encode(f, part['cte'])
+                else:
+                    yield from self._encode(io.BytesIO(part['content']), part['cte'])
+                # encoders are expected to return their own trailing nl
+            else:
+                if part['filepath']:
+                    with open(part['filepath'], 'rb') as f:
+                        yield from iter(partial(f.read, _CHUNK_SIZE), b'')
+                else:
+                    yield part['content']
+                yield self._nl
+
+        yield b'--' + self._boundary + b'--' + self._nl
+
+    def as_fp(self) -> _MultipartReader:
+        """Return a file-like reader that streams multipart content.
+
+        The returned reader supports read() and readinto() for streaming the
+        multipart body without materializing it entirely in memory. This is
+        useful for large file uploads (>2GB).
+        """
+        return _MultipartReader(self.as_iter())
+
+    def as_bytes(self) -> bytes:
+        """Return all multipart content as bytes.
+
+        Warning: This materializes the entire multipart body in memory.
+        For large files, use as_fp() instead to stream the content.
+        """
+        return self.as_fp().read()
+
+    def _generate_header(self, part: _Multipart._Part) -> bytes:
+        buf = io.BytesIO()
+        buf.write(b'--' + self._boundary + self._nl)
+
+        if part['cte']:
+            buf.write(b'Content-Transfer-Encoding: ' + part['cte'] + self._nl)
+        disposition = b'form-data; name="%s"' % part['name']
+        if part['filename']:
+            disposition += b'; filename="%s"' % part['filename']
+        buf.write(b'Content-Type: ' + part['ct'] + self._nl)
+        buf.write(b'Content-Disposition: ' + disposition + self._nl)
+        buf.write(self._nl)
+
+        return buf.getvalue()
+
+    def _encode_base64(self, f: io.RawIOBase | io.BufferedIOBase) -> _t.Generator[bytes, None, None]:
+        """Encode file-like object content as base64, yielding chunks."""
+        # 57 bytes encodes to exactly 76 base64 chars (one line)
+        for chunk in iter(partial(f.read, 57), b''):
+            yield binascii.b2a_base64(chunk, newline=False) + self._nl
+
+    def _encode_passthru(self, f: io.RawIOBase | io.BufferedIOBase) -> _t.Generator[bytes, None, None]:
+        """Read file-like object content as-is, yielding chunks."""
+        yield from iter(partial(f.read, _CHUNK_SIZE), b'')
+        yield self._nl
+
+    def _encode(self, f: io.RawIOBase | io.BufferedIOBase, cte: _CTE) -> _t.Generator[bytes, None, None]:
+        if cte == b'base64':
+            yield from self._encode_base64(f)
+        else:
+            yield from self._encode_passthru(f)
+
+
+def create_multipart(fields: _t.Mapping[str, str | _MultipartField]) -> MultipartProtocol:
+    """Creates a ``MultipartProtocol`` instance from a fields mapping.
+
+    This function processes the fields mapping and returns a ``MultipartProtocol``
+    object that can be used to generate ``multipart/form-data`` bodies.
+    Use this function when you need streaming access to the multipart
+    data (e.g., for large files). For most cases, use ``prepare_multipart()``
+    instead.
+
+    For field format details, see ``prepare_multipart()``.
     """
 
     if not isinstance(fields, Mapping):
@@ -1037,87 +1241,89 @@ def prepare_multipart(fields):
             'Mapping is required, cannot be type %s' % fields.__class__.__name__
         )
 
-    m = email.mime.multipart.MIMEMultipart('form-data')
+    m = _Multipart()
     for field, value in sorted(fields.items()):
         if isinstance(value, str):
-            main_type = 'text'
-            sub_type = 'plain'
-            content = value
-            filename = None
+            m.add(
+                name=to_bytes(field),
+                content=to_bytes(value),
+                ct=_TEXT_CONTENT_TYPE,
+            )
         elif isinstance(value, Mapping):
             filename = value.get('filename')
-            multipart_encoding_str = value.get('multipart_encoding') or 'base64'
             content = value.get('content')
             if not any((filename, content)):
                 raise ValueError('at least one of filename or content must be provided')
 
-            mime = value.get('mime_type')
+            mime: bytes = to_bytes(value.get('mime_type'), nonstring='passthru')
             if not mime:
                 try:
-                    mime = mimetypes.guess_type(filename or '', strict=False)[0] or 'application/octet-stream'
+                    mime = to_bytes(
+                        mimetypes.guess_type(filename or '', strict=False)[0],
+                        nonstring='passthru'
+                    ) or _DEFAULT_MIME_TYPE
                 except Exception:
-                    mime = 'application/octet-stream'
-            main_type, sep, sub_type = mime.partition('/')
+                    mime = _DEFAULT_MIME_TYPE
 
+            cte: _CTE | None
+            if multipart_encoding := value.get('multipart_encoding'):
+                try:
+                    cte = _EncToCTEMap[multipart_encoding]
+                except KeyError:
+                    raise ValueError('multipart_encoding must be one of %s.' % repr(tuple(_EncToCTEMap)))
+            else:
+                cte = None
+
+            if filename and not content:
+                b_filename = to_bytes(filename, errors='surrogate_or_strict')
+                m.add(
+                    name=to_bytes(field),
+                    filename=os.path.basename(b_filename),
+                    filepath=b_filename,
+                    cte=cte,
+                    ct=mime,
+                )
+            else:
+                m.add(
+                    name=to_bytes(field),
+                    filename=to_bytes(filename) if filename else None,
+                    content=to_bytes(content),
+                    cte=cte,
+                    ct=mime,
+                )
         else:
             raise TypeError(
                 'value must be a string, or mapping, cannot be type %s' % value.__class__.__name__
             )
 
-        if not content and filename:
-            multipart_encoding = set_multipart_encoding(multipart_encoding_str)
-            with open(to_bytes(filename, errors='surrogate_or_strict'), 'rb') as f:
-                part = email.mime.application.MIMEApplication(f.read(), _encoder=multipart_encoding)
-                del part['Content-Type']
-                part.add_header('Content-Type', '%s/%s' % (main_type, sub_type))
-        else:
-            part = email.mime.nonmultipart.MIMENonMultipart(main_type, sub_type)
-            part.set_payload(to_bytes(content))
-
-        part.add_header('Content-Disposition', 'form-data')
-        del part['MIME-Version']
-        part.set_param(
-            'name',
-            field,
-            header='Content-Disposition'
-        )
-        if filename:
-            part.set_param(
-                'filename',
-                to_native(os.path.basename(filename)),
-                header='Content-Disposition'
-            )
-
-        m.attach(part)
-
-    # Ensure headers are not split over multiple lines
-    # The HTTP policy also uses CRLF by default
-    b_data = m.as_bytes(policy=email.policy.HTTP)
-    del m
-
-    headers, sep, b_content = b_data.partition(b'\r\n\r\n')
-    del b_data
+    return m
 
-    parser = email.parser.BytesHeaderParser().parsebytes
 
-    return (
-        parser(headers)['content-type'],  # Message converts to native strings
-        b_content
-    )
+def prepare_multipart(fields: _t.Mapping[str, str | _MultipartField]) -> tuple[str, bytes]:
+    """Takes a mapping, and prepares a multipart/form-data body
 
+    Payload content from a file can optionally be encoded when
+    ``multipart_encoding`` is set to 'base64' or '7or8bit'. Without
+    encoding specified, files are sent as-is (binary). The appropriate
+    ``Content-Transfer-Encoding`` and ``Content-Type`` headers will be
+    included.
 
-def set_multipart_encoding(encoding):
-    """Takes an string with specific encoding type for multipart data.
-    Will return reference to function from email.encoders library.
-    If given string key doesn't exist it will raise a ValueError"""
-    encoders_dict = {
-        "base64": email.encoders.encode_base64,
-        "7or8bit": email.encoders.encode_7or8bit
-    }
-    if encoders_dict.get(encoding):
-        return encoders_dict.get(encoding)
-    else:
-        raise ValueError("multipart_encoding must be one of %s." % repr(encoders_dict.keys()))
+    Example:
+        {
+            "file1": {
+                "filename": "/bin/true",
+                "mime_type": "application/octet-stream"
+            },
+            "file2": {
+                "content": "text based file content",
+                "filename": "fake.txt",
+                "mime_type": "text/plain",
+            },
+            "text_form_field": "value"
+        }
+    """
+    m = create_multipart(fields)
+    return m.content_type, m.as_bytes()
 
 
 #
@@ -1382,7 +1588,7 @@ def fetch_file(module, url, data=None, headers=None, method=None,
     :returns: A string, the path to the downloaded file.
     """
     # download file
-    bufsize = 65536
+    bufsize = _CHUNK_SIZE
     parts = urlparse(url)
     file_prefix, file_ext = _split_multiext(os.path.basename(parts.path), count=2)
     fetch_temp_file = tempfile.NamedTemporaryFile(dir=module.tmpdir, prefix=file_prefix, suffix=file_ext, delete=False)
diff --git a/lib/ansible/modules/uri.py b/lib/ansible/modules/uri.py
index ceb6bcae764bac..7835e8cf56d49c 100644
--- a/lib/ansible/modules/uri.py
+++ b/lib/ansible/modules/uri.py
@@ -445,10 +445,10 @@
 from ansible.module_utils.basic import AnsibleModule, sanitize_keys
 from ansible.module_utils.common.text.converters import to_native, to_text
 from ansible.module_utils.urls import (
+    create_multipart,
     fetch_url,
     get_response_filename,
     parse_content_type,
-    prepare_multipart,
     url_argument_spec,
     url_redirect_argument_spec,
 )
@@ -654,7 +654,9 @@ def main():
             dict_headers['Content-Type'] = 'application/x-www-form-urlencoded'
     elif body_format == 'form-multipart':
         try:
-            content_type, body = prepare_multipart(body)
+            multipart = create_multipart(body)
+            content_type = multipart.content_type
+            body = multipart.as_fp()
         except (TypeError, ValueError) as e:
             module.fail_json(msg='failed to parse body as form-multipart: %s' % to_native(e))
         dict_headers['Content-Type'] = content_type
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
