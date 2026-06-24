#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/validating/typechecking.go b/staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/validating/typechecking.go
index 83d0d4c506fae..c8b258f16357f 100644
--- a/staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/validating/typechecking.go
+++ b/staging/src/k8s.io/apiserver/pkg/admission/plugin/policy/validating/typechecking.go
@@ -177,7 +177,7 @@ func (c *TypeChecker) CreateContext(policy *v1.ValidatingAdmissionPolicy) *TypeC
 
 func (c *TypeChecker) compiler(ctx *TypeCheckingContext, typeOverwrite typeOverwrite) (*plugincel.CompositedCompiler, error) {
 	envSet, err := buildEnvSet(
-		/* hasParams */ ctx.paramDeclType != nil,
+		/* hasParams */ !ctx.paramGVK.Empty(),
 		/* hasAuthorizer */ true,
 		typeOverwrite)
 	if err != nil {
@@ -205,7 +205,7 @@ func (c *TypeChecker) CheckExpression(ctx *TypeCheckingContext, expression strin
 			continue
 		}
 		options := plugincel.OptionalVariableDeclarations{
-			HasParams:     ctx.paramDeclType != nil,
+			HasParams:     !ctx.paramGVK.Empty(),
 			HasAuthorizer: true,
 		}
 		compiler.CompileAndStoreVariables(convertv1beta1Variables(ctx.variables), options, environment.StoredExpressions)
@@ -244,7 +244,11 @@ func (c *TypeChecker) declType(gvk schema.GroupVersionKind) (*apiservercel.DeclT
 	if err != nil {
 		return nil, err
 	}
-	return common.SchemaDeclType(&openapi.Schema{Schema: s}, true).MaybeAssignTypeName(generateUniqueTypeName(gvk.Kind)), nil
+	declType := common.SchemaDeclType(&openapi.Schema{Schema: s}, true)
+	if declType == nil {
+		return nil, nil
+	}
+	return declType.MaybeAssignTypeName(generateUniqueTypeName(gvk.Kind)), nil
 }
 
 func (c *TypeChecker) paramsGVK(policy *v1.ValidatingAdmissionPolicy) schema.GroupVersionKind {
@@ -404,12 +408,16 @@ func buildEnvSet(hasParams bool, hasAuthorizer bool, types typeOverwrite) (*envi
 	varOpts = append(varOpts, createVariableOpts(requestType, plugincel.RequestVarName)...)
 
 	// object and oldObject, same type, type(s) resolved from constraints
-	declTypes = append(declTypes, types.object)
+	if types.object != nil {
+		declTypes = append(declTypes, types.object)
+	}
 	varOpts = append(varOpts, createVariableOpts(types.object, plugincel.ObjectVarName, plugincel.OldObjectVarName)...)
 
 	// params, defined by ParamKind
-	if hasParams && types.params != nil {
-		declTypes = append(declTypes, types.params)
+	if hasParams {
+		if types.params != nil {
+			declTypes = append(declTypes, types.params)
+		}
 		varOpts = append(varOpts, createVariableOpts(types.params, plugincel.ParamsVarName)...)
 	}
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
