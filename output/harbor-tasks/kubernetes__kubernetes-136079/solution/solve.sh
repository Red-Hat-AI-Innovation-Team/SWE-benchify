#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/pkg/apis/resource/v1/zz_generated.validations.go b/pkg/apis/resource/v1/zz_generated.validations.go
index b8a1f969bb2bf..4c7596ca97b90 100644
--- a/pkg/apis/resource/v1/zz_generated.validations.go
+++ b/pkg/apis/resource/v1/zz_generated.validations.go
@@ -184,7 +184,26 @@ func Validate_CounterSet(ctx context.Context, op operation.Operation, fldPath *f
 			return
 		}(fldPath.Child("name"), &obj.Name, safe.Field(oldObj, func(oldObj *resourcev1.CounterSet) *string { return &oldObj.Name }), oldObj != nil)...)
 
-	// field resourcev1.CounterSet.Counters has no validation
+	// field resourcev1.CounterSet.Counters
+	errs = append(errs,
+		func(fldPath *field.Path, obj, oldObj map[string]resourcev1.Counter, oldValueCorrelated bool) (errs field.ErrorList) {
+			// don't revalidate unchanged data
+			if oldValueCorrelated && op.Type == operation.Update && equality.Semantic.DeepEqual(obj, oldObj) {
+				return nil
+			}
+			// call field-attached validations
+			earlyReturn := false
+			if e := validate.RequiredMap(ctx, op, fldPath, obj, oldObj); len(e) != 0 {
+				errs = append(errs, e...)
+				earlyReturn = true
+			}
+			if earlyReturn {
+				return // do not proceed
+			}
+			errs = append(errs, validate.EachMapKey(ctx, op, fldPath, obj, oldObj, validate.ShortName)...)
+			return
+		}(fldPath.Child("counters"), obj.Counters, safe.Field(oldObj, func(oldObj *resourcev1.CounterSet) map[string]resourcev1.Counter { return oldObj.Counters }), oldObj != nil)...)
+
 	return errs
 }
 
@@ -899,7 +918,28 @@ func Validate_DeviceCounterConsumption(ctx context.Context, op operation.Operati
 			return
 		}(fldPath.Child("counterSet"), &obj.CounterSet, safe.Field(oldObj, func(oldObj *resourcev1.DeviceCounterConsumption) *string { return &oldObj.CounterSet }), oldObj != nil)...)
 
-	// field resourcev1.DeviceCounterConsumption.Counters has no validation
+	// field resourcev1.DeviceCounterConsumption.Counters
+	errs = append(errs,
+		func(fldPath *field.Path, obj, oldObj map[string]resourcev1.Counter, oldValueCorrelated bool) (errs field.ErrorList) {
+			// don't revalidate unchanged data
+			if oldValueCorrelated && op.Type == operation.Update && equality.Semantic.DeepEqual(obj, oldObj) {
+				return nil
+			}
+			// call field-attached validations
+			earlyReturn := false
+			if e := validate.RequiredMap(ctx, op, fldPath, obj, oldObj); len(e) != 0 {
+				errs = append(errs, e...)
+				earlyReturn = true
+			}
+			if earlyReturn {
+				return // do not proceed
+			}
+			errs = append(errs, validate.EachMapKey(ctx, op, fldPath, obj, oldObj, validate.ShortName)...)
+			return
+		}(fldPath.Child("counters"), obj.Counters, safe.Field(oldObj, func(oldObj *resourcev1.DeviceCounterConsumption) map[string]resourcev1.Counter {
+			return oldObj.Counters
+		}), oldObj != nil)...)
+
 	return errs
 }
 
diff --git a/pkg/apis/resource/v1beta1/zz_generated.validations.go b/pkg/apis/resource/v1beta1/zz_generated.validations.go
index c723674ed2b7c..8e03697cd5765 100644
--- a/pkg/apis/resource/v1beta1/zz_generated.validations.go
+++ b/pkg/apis/resource/v1beta1/zz_generated.validations.go
@@ -303,7 +303,26 @@ func Validate_CounterSet(ctx context.Context, op operation.Operation, fldPath *f
 			return
 		}(fldPath.Child("name"), &obj.Name, safe.Field(oldObj, func(oldObj *resourcev1beta1.CounterSet) *string { return &oldObj.Name }), oldObj != nil)...)
 
-	// field resourcev1beta1.CounterSet.Counters has no validation
+	// field resourcev1beta1.CounterSet.Counters
+	errs = append(errs,
+		func(fldPath *field.Path, obj, oldObj map[string]resourcev1beta1.Counter, oldValueCorrelated bool) (errs field.ErrorList) {
+			// don't revalidate unchanged data
+			if oldValueCorrelated && op.Type == operation.Update && equality.Semantic.DeepEqual(obj, oldObj) {
+				return nil
+			}
+			// call field-attached validations
+			earlyReturn := false
+			if e := validate.RequiredMap(ctx, op, fldPath, obj, oldObj); len(e) != 0 {
+				errs = append(errs, e...)
+				earlyReturn = true
+			}
+			if earlyReturn {
+				return // do not proceed
+			}
+			errs = append(errs, validate.EachMapKey(ctx, op, fldPath, obj, oldObj, validate.ShortName)...)
+			return
+		}(fldPath.Child("counters"), obj.Counters, safe.Field(oldObj, func(oldObj *resourcev1beta1.CounterSet) map[string]resourcev1beta1.Counter { return oldObj.Counters }), oldObj != nil)...)
+
 	return errs
 }
 
@@ -939,7 +958,28 @@ func Validate_DeviceCounterConsumption(ctx context.Context, op operation.Operati
 			return
 		}(fldPath.Child("counterSet"), &obj.CounterSet, safe.Field(oldObj, func(oldObj *resourcev1beta1.DeviceCounterConsumption) *string { return &oldObj.CounterSet }), oldObj != nil)...)
 
-	// field resourcev1beta1.DeviceCounterConsumption.Counters has no validation
+	// field resourcev1beta1.DeviceCounterConsumption.Counters
+	errs = append(errs,
+		func(fldPath *field.Path, obj, oldObj map[string]resourcev1beta1.Counter, oldValueCorrelated bool) (errs field.ErrorList) {
+			// don't revalidate unchanged data
+			if oldValueCorrelated && op.Type == operation.Update && equality.Semantic.DeepEqual(obj, oldObj) {
+				return nil
+			}
+			// call field-attached validations
+			earlyReturn := false
+			if e := validate.RequiredMap(ctx, op, fldPath, obj, oldObj); len(e) != 0 {
+				errs = append(errs, e...)
+				earlyReturn = true
+			}
+			if earlyReturn {
+				return // do not proceed
+			}
+			errs = append(errs, validate.EachMapKey(ctx, op, fldPath, obj, oldObj, validate.ShortName)...)
+			return
+		}(fldPath.Child("counters"), obj.Counters, safe.Field(oldObj, func(oldObj *resourcev1beta1.DeviceCounterConsumption) map[string]resourcev1beta1.Counter {
+			return oldObj.Counters
+		}), oldObj != nil)...)
+
 	return errs
 }
 
diff --git a/pkg/apis/resource/v1beta2/zz_generated.validations.go b/pkg/apis/resource/v1beta2/zz_generated.validations.go
index 39ce4a175509d..a8124512c9aad 100644
--- a/pkg/apis/resource/v1beta2/zz_generated.validations.go
+++ b/pkg/apis/resource/v1beta2/zz_generated.validations.go
@@ -186,7 +186,26 @@ func Validate_CounterSet(ctx context.Context, op operation.Operation, fldPath *f
 			return
 		}(fldPath.Child("name"), &obj.Name, safe.Field(oldObj, func(oldObj *resourcev1beta2.CounterSet) *string { return &oldObj.Name }), oldObj != nil)...)
 
-	// field resourcev1beta2.CounterSet.Counters has no validation
+	// field resourcev1beta2.CounterSet.Counters
+	errs = append(errs,
+		func(fldPath *field.Path, obj, oldObj map[string]resourcev1beta2.Counter, oldValueCorrelated bool) (errs field.ErrorList) {
+			// don't revalidate unchanged data
+			if oldValueCorrelated && op.Type == operation.Update && equality.Semantic.DeepEqual(obj, oldObj) {
+				return nil
+			}
+			// call field-attached validations
+			earlyReturn := false
+			if e := validate.RequiredMap(ctx, op, fldPath, obj, oldObj); len(e) != 0 {
+				errs = append(errs, e...)
+				earlyReturn = true
+			}
+			if earlyReturn {
+				return // do not proceed
+			}
+			errs = append(errs, validate.EachMapKey(ctx, op, fldPath, obj, oldObj, validate.ShortName)...)
+			return
+		}(fldPath.Child("counters"), obj.Counters, safe.Field(oldObj, func(oldObj *resourcev1beta2.CounterSet) map[string]resourcev1beta2.Counter { return oldObj.Counters }), oldObj != nil)...)
+
 	return errs
 }
 
@@ -913,7 +932,28 @@ func Validate_DeviceCounterConsumption(ctx context.Context, op operation.Operati
 			return
 		}(fldPath.Child("counterSet"), &obj.CounterSet, safe.Field(oldObj, func(oldObj *resourcev1beta2.DeviceCounterConsumption) *string { return &oldObj.CounterSet }), oldObj != nil)...)
 
-	// field resourcev1beta2.DeviceCounterConsumption.Counters has no validation
+	// field resourcev1beta2.DeviceCounterConsumption.Counters
+	errs = append(errs,
+		func(fldPath *field.Path, obj, oldObj map[string]resourcev1beta2.Counter, oldValueCorrelated bool) (errs field.ErrorList) {
+			// don't revalidate unchanged data
+			if oldValueCorrelated && op.Type == operation.Update && equality.Semantic.DeepEqual(obj, oldObj) {
+				return nil
+			}
+			// call field-attached validations
+			earlyReturn := false
+			if e := validate.RequiredMap(ctx, op, fldPath, obj, oldObj); len(e) != 0 {
+				errs = append(errs, e...)
+				earlyReturn = true
+			}
+			if earlyReturn {
+				return // do not proceed
+			}
+			errs = append(errs, validate.EachMapKey(ctx, op, fldPath, obj, oldObj, validate.ShortName)...)
+			return
+		}(fldPath.Child("counters"), obj.Counters, safe.Field(oldObj, func(oldObj *resourcev1beta2.DeviceCounterConsumption) map[string]resourcev1beta2.Counter {
+			return oldObj.Counters
+		}), oldObj != nil)...)
+
 	return errs
 }
 
diff --git a/pkg/apis/resource/validation/validation.go b/pkg/apis/resource/validation/validation.go
index 8faebfc3cb39f..e05d8ce2c3c0f 100644
--- a/pkg/apis/resource/validation/validation.go
+++ b/pkg/apis/resource/validation/validation.go
@@ -780,7 +780,7 @@ func validateCounterSet(counterSet resource.CounterSet, fldPath *field.Path) fie
 	} else {
 		// The size limit is enforced for across all sets by the caller.
 		allErrs = append(allErrs, validateMap(counterSet.Counters, resource.ResourceSliceMaxCountersPerCounterSet, validation.DNS1123LabelMaxLength,
-			validateCounterName, validateDeviceCounter, fldPath.Child("counters"))...)
+			validateCounterName, validateDeviceCounter, fldPath.Child("counters"), keysCovered)...)
 	}
 
 	return allErrs
@@ -880,7 +880,7 @@ func validateDeviceCounterConsumption(deviceCounterConsumption resource.DeviceCo
 		allErrs = append(allErrs, field.Required(fldPath.Child("counters"), ""))
 	} else {
 		allErrs = append(allErrs, validateMap(deviceCounterConsumption.Counters, resource.ResourceSliceMaxCountersPerDeviceCounterConsumption,
-			validation.DNS1123LabelMaxLength, validateCounterName, validateDeviceCounter, fldPath.Child("counters"))...)
+			validation.DNS1123LabelMaxLength, validateCounterName, validateDeviceCounter, fldPath.Child("counters"), keysCovered)...)
 	}
 	return allErrs
 }
@@ -1154,6 +1154,8 @@ const (
 	sizeCovered
 	// The uniqueness check is covered by declarative validation.
 	uniquenessCovered
+	// key validation is covered by declarative validation.
+	keysCovered
 )
 
 // validateItems validates each item in a slice.
@@ -1240,7 +1242,7 @@ func quantityKey(item apiresource.Quantity) string {
 // small limit gets increased because it is okay to include more details.
 // This is not used for validation of keys, which has to be done by
 // the callback function.
-func validateMap[K ~string, T any](m map[K]T, maxSize, truncateKeyLen int, validateKey func(K, *field.Path) field.ErrorList, validateItem func(T, *field.Path) field.ErrorList, fldPath *field.Path) field.ErrorList {
+func validateMap[K ~string, T any](m map[K]T, maxSize, truncateKeyLen int, validateKey func(K, *field.Path) field.ErrorList, validateItem func(T, *field.Path) field.ErrorList, fldPath *field.Path, opts ...validationOption) field.ErrorList {
 	var allErrs field.ErrorList
 	if maxSize >= 0 && len(m) > maxSize {
 		allErrs = append(allErrs, field.TooMany(fldPath, len(m), maxSize))
@@ -1249,7 +1251,12 @@ func validateMap[K ~string, T any](m map[K]T, maxSize, truncateKeyLen int, valid
 	}
 	for key, item := range m {
 		keyPath := fldPath.Key(truncateIfTooLong(string(key), truncateKeyLen))
-		allErrs = append(allErrs, validateKey(key, keyPath)...)
+
+		keyValidationErrors := validateKey(key, fldPath)
+		if slices.Contains(opts, keysCovered) {
+			keyValidationErrors = keyValidationErrors.MarkCoveredByDeclarative()
+		}
+		allErrs = append(allErrs, keyValidationErrors...)
 		allErrs = append(allErrs, validateItem(item, keyPath)...)
 	}
 	return allErrs
diff --git a/staging/src/k8s.io/api/resource/v1/generated.proto b/staging/src/k8s.io/api/resource/v1/generated.proto
index c254137c43bd7..5cf35c20a735a 100644
--- a/staging/src/k8s.io/api/resource/v1/generated.proto
+++ b/staging/src/k8s.io/api/resource/v1/generated.proto
@@ -317,6 +317,8 @@ message CounterSet {
   // The maximum number of counters is 32.
   //
   // +required
+  // +k8s:required
+  // +k8s:eachKey=+k8s:format=k8s-short-name
   map<string, Counter> counters = 2;
 }
 
@@ -798,6 +800,8 @@ message DeviceCounterConsumption {
   // The maximum number of counters is 32.
   //
   // +required
+  // +k8s:required
+  // +k8s:eachKey=+k8s:format=k8s-short-name
   map<string, Counter> counters = 2;
 }
 
diff --git a/staging/src/k8s.io/api/resource/v1/types.go b/staging/src/k8s.io/api/resource/v1/types.go
index 29b4a5fbaccbf..44a92fc19509b 100644
--- a/staging/src/k8s.io/api/resource/v1/types.go
+++ b/staging/src/k8s.io/api/resource/v1/types.go
@@ -215,6 +215,8 @@ type CounterSet struct {
 	// The maximum number of counters is 32.
 	//
 	// +required
+	// +k8s:required
+	// +k8s:eachKey=+k8s:format=k8s-short-name
 	Counters map[string]Counter `json:"counters,omitempty" protobuf:"bytes,2,name=counters"`
 }
 
@@ -448,6 +450,8 @@ type DeviceCounterConsumption struct {
 	// The maximum number of counters is 32.
 	//
 	// +required
+	// +k8s:required
+	// +k8s:eachKey=+k8s:format=k8s-short-name
 	Counters map[string]Counter `json:"counters,omitempty" protobuf:"bytes,2,opt,name=counters"`
 }
 
diff --git a/staging/src/k8s.io/api/resource/v1beta1/generated.proto b/staging/src/k8s.io/api/resource/v1beta1/generated.proto
index 5fb359693928a..70bcf7987c775 100644
--- a/staging/src/k8s.io/api/resource/v1beta1/generated.proto
+++ b/staging/src/k8s.io/api/resource/v1beta1/generated.proto
@@ -458,6 +458,8 @@ message CounterSet {
   // The maximum number of counters is 32.
   //
   // +required
+  // +k8s:required
+  // +k8s:eachKey=+k8s:format=k8s-short-name
   map<string, Counter> counters = 2;
 }
 
@@ -807,6 +809,8 @@ message DeviceCounterConsumption {
   // The maximum number of counters is 32.
   //
   // +required
+  // +k8s:required
+  // +k8s:eachKey=+k8s:format=k8s-short-name
   map<string, Counter> counters = 2;
 }
 
diff --git a/staging/src/k8s.io/api/resource/v1beta1/types.go b/staging/src/k8s.io/api/resource/v1beta1/types.go
index 4c8ee214a0188..37d9923eaaf30 100644
--- a/staging/src/k8s.io/api/resource/v1beta1/types.go
+++ b/staging/src/k8s.io/api/resource/v1beta1/types.go
@@ -215,6 +215,8 @@ type CounterSet struct {
 	// The maximum number of counters is 32.
 	//
 	// +required
+	// +k8s:required
+	// +k8s:eachKey=+k8s:format=k8s-short-name
 	Counters map[string]Counter `json:"counters,omitempty" protobuf:"bytes,2,name=counters"`
 }
 
@@ -465,6 +467,8 @@ type DeviceCounterConsumption struct {
 	// The maximum number of counters is 32.
 	//
 	// +required
+	// +k8s:required
+	// +k8s:eachKey=+k8s:format=k8s-short-name
 	Counters map[string]Counter `json:"counters,omitempty" protobuf:"bytes,2,opt,name=counters"`
 }
 
diff --git a/staging/src/k8s.io/api/resource/v1beta2/generated.proto b/staging/src/k8s.io/api/resource/v1beta2/generated.proto
index 76af5aa4e205d..c5fd95b7d8ee0 100644
--- a/staging/src/k8s.io/api/resource/v1beta2/generated.proto
+++ b/staging/src/k8s.io/api/resource/v1beta2/generated.proto
@@ -317,6 +317,8 @@ message CounterSet {
   // The maximum number of counters is 32.
   //
   // +required
+  // +k8s:required
+  // +k8s:eachKey=+k8s:format=k8s-short-name
   map<string, Counter> counters = 2;
 }
 
@@ -798,6 +800,8 @@ message DeviceCounterConsumption {
   // The maximum number of counters is 32.
   //
   // +required
+  // +k8s:required
+  // +k8s:eachKey=+k8s:format=k8s-short-name
   map<string, Counter> counters = 2;
 }
 
diff --git a/staging/src/k8s.io/api/resource/v1beta2/types.go b/staging/src/k8s.io/api/resource/v1beta2/types.go
index 49534348843ce..8bb62f71a29a0 100644
--- a/staging/src/k8s.io/api/resource/v1beta2/types.go
+++ b/staging/src/k8s.io/api/resource/v1beta2/types.go
@@ -215,6 +215,8 @@ type CounterSet struct {
 	// The maximum number of counters is 32.
 	//
 	// +required
+	// +k8s:required
+	// +k8s:eachKey=+k8s:format=k8s-short-name
 	Counters map[string]Counter `json:"counters,omitempty" protobuf:"bytes,2,name=counters"`
 }
 
@@ -448,6 +450,8 @@ type DeviceCounterConsumption struct {
 	// The maximum number of counters is 32.
 	//
 	// +required
+	// +k8s:required
+	// +k8s:eachKey=+k8s:format=k8s-short-name
 	Counters map[string]Counter `json:"counters,omitempty" protobuf:"bytes,2,opt,name=counters"`
 }
 
diff --git a/staging/src/k8s.io/code-generator/cmd/validation-gen/validators/each.go b/staging/src/k8s.io/code-generator/cmd/validation-gen/validators/each.go
index 4961f46d26dbc..bbdc08204cac0 100644
--- a/staging/src/k8s.io/code-generator/cmd/validation-gen/validators/each.go
+++ b/staging/src/k8s.io/code-generator/cmd/validation-gen/validators/each.go
@@ -269,7 +269,7 @@ func (ektv eachKeyTagValidator) GetValidations(context Context, tag codetags.Tag
 
 	elemContext := Context{
 		Scope:      ScopeMapKey,
-		Type:       nt.Elem,
+		Type:       nt.Key,
 		Path:       context.Path.Key("(keys)"),
 		Member:     nil, // NA for map keys
 		ParentPath: context.Path,
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
