#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/kubectl/pkg/cmd/apply/apply.go b/staging/src/k8s.io/kubectl/pkg/cmd/apply/apply.go
index d509b90f3e36c..f07b644edb0d8 100644
--- a/staging/src/k8s.io/kubectl/pkg/cmd/apply/apply.go
+++ b/staging/src/k8s.io/kubectl/pkg/cmd/apply/apply.go
@@ -725,36 +725,43 @@ See https://kubernetes.io/docs/reference/using-api/server-side-apply/#conflicts`
 		return err
 	}
 
+	metadata, _ := meta.Accessor(info.Object)
+	annotationMap := metadata.GetAnnotations()
+	if _, ok := annotationMap[corev1.LastAppliedConfigAnnotation]; !ok {
+		fmt.Fprintf(o.ErrOut, warningNoLastAppliedConfigAnnotation, info.ObjectName(), corev1.LastAppliedConfigAnnotation, o.cmdBaseName) //nolint:errcheck
+	}
+
+	patcher, err := newPatcher(o, info, helper)
+	if err != nil {
+		return err
+	}
+
+	var patchBytes []byte
+	var patchedObject runtime.Object
+
 	if o.DryRunStrategy != cmdutil.DryRunClient {
-		metadata, _ := meta.Accessor(info.Object)
-		annotationMap := metadata.GetAnnotations()
-		if _, ok := annotationMap[corev1.LastAppliedConfigAnnotation]; !ok {
-			fmt.Fprintf(o.ErrOut, warningNoLastAppliedConfigAnnotation, info.ObjectName(), corev1.LastAppliedConfigAnnotation, o.cmdBaseName)
-		}
+		patchBytes, patchedObject, err = patcher.Patch(info.Object, modified, info.Source, info.Namespace, info.Name, o.ErrOut)
+	} else {
+		patchBytes, patchedObject, err = patcher.PatchLocal(info.Object, modified, o.ErrOut)
+	}
 
-		patcher, err := newPatcher(o, info, helper)
-		if err != nil {
-			return err
-		}
-		patchBytes, patchedObject, err := patcher.Patch(info.Object, modified, info.Source, info.Namespace, info.Name, o.ErrOut)
-		if err != nil {
-			return cmdutil.AddSourceToErr(fmt.Sprintf("applying patch:\n%s\nto:\n%v\nfor:", patchBytes, info), info.Source, err)
-		}
+	if err != nil {
+		return cmdutil.AddSourceToErr(fmt.Sprintf("applying patch:\n%s\nto:\n%v\nfor:", patchBytes, info), info.Source, err)
+	}
 
-		info.Refresh(patchedObject, true)
+	info.Refresh(patchedObject, true) //nolint:errcheck
 
-		WarnIfDeleting(info.Object, o.ErrOut)
+	WarnIfDeleting(info.Object, o.ErrOut)
 
-		if string(patchBytes) == "{}" && !o.shouldPrintObject() {
-			printer, err := o.ToPrinter("unchanged")
-			if err != nil {
-				return err
-			}
-			if err = printer.PrintObj(info.Object, o.Out); err != nil {
-				return err
-			}
-			return nil
+	if string(patchBytes) == "{}" && !o.shouldPrintObject() {
+		printer, err := o.ToPrinter("unchanged")
+		if err != nil {
+			return err
 		}
+		if err = printer.PrintObj(info.Object, o.Out); err != nil {
+			return err
+		}
+		return nil
 	}
 
 	if o.shouldPrintObject() {
diff --git a/staging/src/k8s.io/kubectl/pkg/cmd/apply/patcher.go b/staging/src/k8s.io/kubectl/pkg/cmd/apply/patcher.go
index c5b99ce6644be..6d9d7ec22e806 100644
--- a/staging/src/k8s.io/kubectl/pkg/cmd/apply/patcher.go
+++ b/staging/src/k8s.io/kubectl/pkg/cmd/apply/patcher.go
@@ -24,6 +24,7 @@ import (
 	"time"
 
 	"github.com/jonboulle/clockwork"
+	jsonpatch "gopkg.in/evanphx/json-patch.v4"
 	apierrors "k8s.io/apimachinery/pkg/api/errors"
 	"k8s.io/apimachinery/pkg/api/meta"
 	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
@@ -114,7 +115,7 @@ func (p *Patcher) delete(namespace, name string) error {
 	return err
 }
 
-func (p *Patcher) patchSimple(obj runtime.Object, modified []byte, namespace, name string, errOut io.Writer) ([]byte, runtime.Object, error) {
+func (p *Patcher) patchSimple(obj runtime.Object, modified []byte, namespace, name string, errOut io.Writer, localApply bool) ([]byte, runtime.Object, error) {
 	// Serialize the current configuration of the object from the server.
 	current, err := runtime.Encode(unstructured.UnstructuredJSONScheme, obj)
 	if err != nil {
@@ -195,6 +196,24 @@ func (p *Patcher) patchSimple(obj runtime.Object, modified []byte, namespace, na
 		return patch, obj, nil
 	}
 
+	if localApply {
+		var patchedBytes []byte
+		if patchType == types.StrategicMergePatchType {
+			versionedObj, _ := scheme.Scheme.New(p.Mapping.GroupVersionKind)
+			patchedBytes, err = strategicpatch.StrategicMergePatch(current, patch, versionedObj)
+		} else {
+			patchedBytes, err = jsonpatch.MergePatch(current, patch)
+		}
+		if err != nil {
+			return nil, nil, fmt.Errorf("applying patch locally: %w", err)
+		}
+		patchedObj, _, err := unstructured.UnstructuredJSONScheme.Decode(patchedBytes, nil, nil)
+		if err != nil {
+			return nil, nil, fmt.Errorf("decoding locally patched object: %w", err)
+		}
+		return patch, patchedObj, nil
+	}
+
 	if p.ResourceVersion != nil {
 		patch, err = addResourceVersion(patch, *p.ResourceVersion)
 		if err != nil {
@@ -357,7 +376,7 @@ func (p *Patcher) buildStrategicMergeFromBuiltins(versionedObj runtime.Object, o
 // the final patched object. On failure, returns an error.
 func (p *Patcher) Patch(current runtime.Object, modified []byte, source, namespace, name string, errOut io.Writer) ([]byte, runtime.Object, error) {
 	var getErr error
-	patchBytes, patchObject, err := p.patchSimple(current, modified, namespace, name, errOut)
+	patchBytes, patchObject, err := p.patchSimple(current, modified, namespace, name, errOut, false)
 	if p.Retries == 0 {
 		p.Retries = maxPatchRetry
 	}
@@ -369,7 +388,7 @@ func (p *Patcher) Patch(current runtime.Object, modified []byte, source, namespa
 		if getErr != nil {
 			return nil, nil, getErr
 		}
-		patchBytes, patchObject, err = p.patchSimple(current, modified, namespace, name, errOut)
+		patchBytes, patchObject, err = p.patchSimple(current, modified, namespace, name, errOut, false)
 	}
 	if err != nil {
 		if (apierrors.IsConflict(err) || apierrors.IsInvalid(err)) && p.Force {
@@ -381,6 +400,12 @@ func (p *Patcher) Patch(current runtime.Object, modified []byte, source, namespa
 	return patchBytes, patchObject, err
 }
 
+// PatchLocal computes and applies the patch locally without sending to the server.
+// Used for --dry-run=client.
+func (p *Patcher) PatchLocal(current runtime.Object, modified []byte, errOut io.Writer) ([]byte, runtime.Object, error) {
+	return p.patchSimple(current, modified, "", "", errOut, true)
+}
+
 func (p *Patcher) deleteAndCreate(original runtime.Object, modified []byte, namespace, name string) ([]byte, runtime.Object, error) {
 	if err := p.delete(namespace, name); err != nil {
 		return modified, nil, err
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
