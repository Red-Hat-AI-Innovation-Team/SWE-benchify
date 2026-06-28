URI multipart file size limitation
### Summary

When uploading larger files using builtin.uri using form/multipart, the upload fails after 2 GB

found a similar issue here: https://groups.google.com/g/ansible-project/c/tnx6Po206VM

However, looks like it has to to with the python httplib ?!
https://github.com/psf/requests/issues/2717#issuecomment-724725392

### Issue Type

Bug Report

### Component Name

builtin.uri

### Ansible Version

```console
$ ansible --version
ansible 2.10.15
  config file = None
  configured module search path = ['/root/.ansible/plugins/modules', '/usr/share/ansible/plugins/modules']
  ansible python module location = /usr/lib/python3.9/site-packages/ansible
  executable location = /usr/bin/ansible
  python version = 3.9.7 (default, Nov 24 2021, 21:15:59) [GCC 10.3.1 20211027]
```


### Configuration

```console
$ ansible-config dump --only-changed
```


### OS / Environment

Alpine Linux v3.15

### Steps to Reproduce

<!--- Paste example playbooks or commands between quotes below -->
```yaml (paste below)
- name: Upload Upgrade File, this may take a while
  uri:
    method: POST
    url: "{{ ppdm_baseurl }}:{{ ppdm_port }}{{ ppdm_api_ver }}/upgrade-packages"
    body_format: form-multipart
    body: 
      file:
        filename: "{{ upload_file }}"
      mime_type: application/octet-stream  
    headers:
      Content-Type: multipart/form-data
      authorization: "Bearer {{ access_token }}"    
    status_code: 200,202,403
    validate_certs: false
  register: result  
  when: not ansible_check_mode 
- set_fact:
    upload_result: "{{ result.json }}"
- debug:
    msg: "{{ upload_result }}"
    verbosity: 0
```


### Expected Results

I expect the octet/stream to upload the file as chunks

### Actual Results

```console
The full traceback is:
Traceback (most recent call last):
  File "/tmp/ansible_ansible.legacy.uri_payload__3xqgmdq/ansible_ansible.legacy.uri_payload.zip/ansible/module_utils/urls.py", line 1611, in fetch_url
    r = open_url(url, data=data, headers=headers, method=method,
  File "/tmp/ansible_ansible.legacy.uri_payload__3xqgmdq/ansible_ansible.legacy.uri_payload.zip/ansible/module_utils/urls.py", line 1393, in open_url
    return Request().open(method, url, data=data, headers=headers, use_proxy=use_proxy,
  File "/tmp/ansible_ansible.legacy.uri_payload__3xqgmdq/ansible_ansible.legacy.uri_payload.zip/ansible/module_utils/urls.py", line 1304, in open
    return urllib_request.urlopen(request, None, timeout)
  File "/usr/lib/python3.9/urllib/request.py", line 214, in urlopen
    return opener.open(url, data, timeout)
  File "/usr/lib/python3.9/urllib/request.py", line 517, in open
    response = self._open(req, data)
  File "/usr/lib/python3.9/urllib/request.py", line 534, in _open
    result = self._call_chain(self.handle_open, protocol, protocol +
  File "/usr/lib/python3.9/urllib/request.py", line 494, in _call_chain
    result = func(*args)
  File "/tmp/ansible_ansible.legacy.uri_payload__3xqgmdq/ansible_ansible.legacy.uri_payload.zip/ansible/module_utils/urls.py", line 483, in https_open
    return self.do_open(self._build_https_connection, req)
  File "/usr/lib/python3.9/urllib/request.py", line 1346, in do_open
    h.request(req.get_method(), req.selector, req.data, headers,
  File "/usr/lib/python3.9/http/client.py", line 1279, in request
    self._send_request(method, url, body, headers, encode_chunked)
  File "/usr/lib/python3.9/http/client.py", line 1325, in _send_request
    self.endheaders(body, encode_chunked=encode_chunked)
  File "/usr/lib/python3.9/http/client.py", line 1274, in endheaders
    self._send_output(message_body, encode_chunked=encode_chunked)
  File "/usr/lib/python3.9/http/client.py", line 1073, in _send_output
    self.send(chunk)
  File "/usr/lib/python3.9/http/client.py", line 995, in send
    self.sock.sendall(data)
  File "/usr/lib/python3.9/ssl.py", line 1204, in sendall
    v = self.send(byte_view[count:])
  File "/usr/lib/python3.9/ssl.py", line 1173, in send
    return self._sslobj.write(data)
OverflowError: string longer than 2147483647 bytes
fatal: [localhost]: FAILED! => {
    "changed": false,
    "elapsed": 0,
    "invocation": {
        "module_args": {
            "attributes": null,
            "body": {
                "file": {
                    "filename": "/root/.ansible/tmp/ansible-tmp-1641464672.1413147-225-255711373493873/dellemc-ppdm-upgrade-sw-19.9.0-17.pkg"
                },
                "mime_type": "application/octet-stream"
            },
            "body_format": "form-multipart",
            "client_cert": null,
            "client_key": null,
            "creates": null,
            "dest": null,
            "follow_redirects": "safe",
            "force": false,
            "force_basic_auth": false,
            "group": null,
            "headers": {
                "Content-Type": "multipart/form-data; boundary=\"===============9138599903283805365==\"",
                "authorization": "redacted"
            },
            "http_agent": "ansible-httpget",
            "method": "POST",
            "mode": null,
            "owner": null,
            "remote_src": false,
            "removes": null,
            "return_content": false,
            "selevel": null,
            "serole": null,
            "setype": null,
            "seuser": null,
            "src": null,
            "status_code": [
                "200",
                "202",
                "403"
            ],
            "timeout": 30,
            "unix_socket": null,
            "unsafe_writes": false,
            "url": "https://redacted:8443/api/v2/upgrade-packages",
            "url_password": null,
            "url_username": null,
            "use_proxy": true,
            "validate_certs": false
        }
    },
    "msg": "Status code was -1 and not [200, 202, 403]: An unknown error occurred: string longer than 2147483647 bytes",
    "redirected": false,
    "status": -1,
    "url": "redacted"
}
```


### Code of Conduct

- [X] I agree to follow the Ansible Code of Conduct

**Repository:** `ansible/ansible`
**Base commit:** `776f90ae4b03fa02cdbf866e5268070d745715a8`

## Hints

Files identified in the description:
None

If these files are incorrect, please update the `component name` section of the description or use the `!component` bot command.

[click here for bot help](https://github.com/ansible/ansibullbot/blob/devel/ISSUE_HELP.md)
<!--- boilerplate: components_banner --->

I believe the most simple solution would be to modify the `uri` module to add:

```
body = io.BytesIO(body)
```

<details>
<summary>Patch...</summary>
<p>

```diff
diff --git a/lib/ansible/modules/uri.py b/lib/ansible/modules/uri.py
index dd42f7eb60..01e78680e2 100644
--- a/lib/ansible/modules/uri.py
+++ b/lib/ansible/modules/uri.py
@@ -427,6 +427,7 @@ url:
 '''

 import datetime
+import io
 import json
 import os
 import re
@@ -669,6 +670,8 @@ def main():
             content_type, body = prepare_multipart(body)
         except (TypeError, ValueError) as e:
             module.fail_json(msg='failed to parse body as form-multipart: %s' % to_native(e))
+        else:
+            body = io.BytesIO(body)
         dict_headers['Content-Type'] = content_type

     if creates is not None:
```

</p>
</details>

Hi all,

I would like to reproduce this issue. Is there a server/2GB+ sample file I could try uploading?

I'm unable to reproduce the exact ssl overflow error.
But 2.5GB file caused below problem while my server has 16GB RAM. It doesn't happen with small files.
```
fatal: [x.x.x.x]: FAILED! => {
    "changed": false,
    "module_stderr": "Shared connection to x.x.x.x closed.\r\n",
    "module_stdout": "Killed\r\n",
    "msg": "MODULE FAILURE\nSee stdout/stderr for the exact error",
    "rc": 137
}
```

It can be fixed by using BytesIO when reading the file in `prepare_multipart(fields)`:
```
# debug_dir/ansible/module_utils/urls.py

1645         if not content and filename:
1646             with open(to_bytes(filename, errors='surrogate_or_strict'), 'rb') as f:
1647                 bytes_obj = io.BytesIO(f.read())
1648                 part = email.mime.application.MIMEApplication(bytes_obj.getbuffer())

```
Should I raise a separate issue for this?

P.S Adding suggested fix does not affect the results, but need to add `getbuffer()`
```
+        else:
+            body = io.BytesIO(body).getbuffer()
```
**Environment:**
Test file: `fallocate -l 2500MB 2GBfile`
Backend: 
```
Django==4.0.6
django-sslserver==0.22
djangorestframework==3.13.1
```
```
ansible [core 2.13.2]
  config file = None
  configured module search path = ['/home/artur/.ansible/plugins/modules', '/usr/share/ansible/plugins/modules']
  ansible python module location = /home/artur/.local/lib/python3.10/site-packages/ansible
  ansible collection location = /home/artur/.ansible/collections:/usr/share/ansible/collections
  executable location = /home/artur/.local/bin/ansible
  python version = 3.10.4 (main, Jun 29 2022, 12:14:53) [GCC 11.2.0]
  jinja version = 3.0.3
  libyaml = True
```


Should I try to work on this based on what @sivel suggested?

As of yesterday I have started working on some multipart changes including this.

> I would like to reproduce this issue. Is there a server/2GB+ sample file I could try uploading?

@njthanhtrang 
fastest way is using a tool like dd on your maschine:
`$ dd if=/dev/urandom of=DATABLOB.bin bs=1024 count=2M`

or just write zeroes:
`$ dd if=/dev/zero of=DATABLOB.bin bs=1024 count=2Ms`

```
$ du -h DATABLOB.bin
2.1G    DATABLOB.bin
```
