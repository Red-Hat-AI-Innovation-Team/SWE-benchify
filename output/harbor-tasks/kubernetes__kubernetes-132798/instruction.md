Improve error messages for CEL validation
### What would you like to be added?

When I use CEL validation as of today I get messages that not easy to parse for users, e.g.

```
* spec.name: Invalid value: "string": name must consist of lower case alphanumeric characters
* spec.pods: Invalid value: "array": entries in pods must be unique
```

More specifically, looks “string” or "array" is not reporting the actual value of the field but the field type.

This can be reproduced by creating a kind cluster (I used K8s v1.32.0), applying the following CRD:

```
---
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  annotations:
    controller-gen.kubebuilder.io/version: v0.18.0
  name: testresources.test.cluster.x-k8s.io
spec:
  group: test.cluster.x-k8s.io
  names:
    kind: TestResource
    listKind: TestResourceList
    plural: testresources
    singular: testresource
  scope: Namespaced
  versions:
  - name: v1beta1
    schema:
      openAPIV3Schema:
        description: TestResource defines a test resource.
        properties:
          apiVersion:
            description: |-
              APIVersion defines the versioned schema of this representation of an object.
              Servers should convert recognized schemas to the latest internal value, and
              may reject unrecognized values.
              More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#resources
            type: string
          kind:
            description: |-
              Kind is a string value representing the REST resource this object represents.
              Servers may infer this from the endpoint the client submits requests to.
              Cannot be updated.
              In CamelCase.
              More info: https://git.k8s.io/community/contributors/devel/sig-architecture/api-conventions.md#types-kinds
            type: string
          metadata:
            type: object
          spec:
            description: TestResourceSpec defines the resource spec.
            properties:
              name:
                maxLength: 253
                minLength: 1
                type: string
                x-kubernetes-validations:
                - message: name must consist of lower case alphanumeric characters
                  rule: self.matches('^[a-z0-9]*$')
              pods:
                items:
                  maxLength: 256
                  minLength: 1
                  type: string
                maxItems: 32
                minItems: 1
                type: array
                x-kubernetes-list-type: atomic
                x-kubernetes-validations:
                - message: entries in pods must be unique
                  rule: self.all(x, self.exists_one(y, x == y))
            required:
            - name
            type: object
          status:
            description: TestResourceStatus defines the status of a TestResource.
            properties:
              availableReplicas:
                format: int32
                type: integer
              readyReplicas:
                format: int32
                type: integer
              replicas:
                format: int32
                type: integer
              upToDateReplicas:
                format: int32
                type: integer
              version:
                maxLength: 256
                minLength: 1
                type: string
            type: object
        type: object
    served: true
    storage: true
    subresources:
      status: {}
```

And then the following yaml to create an invalid resource

```yml
apiVersion: test.cluster.x-k8s.io/v1beta1
kind: TestResource
metadata:
  name: invalid
spec:
  name: $__
  pods:
    - foo
    - foo
```


FYI there was some discussion in https://kubernetes.slack.com/archives/C02TTBG6LF4/p1750091061651119 about this issue, capturing here some relevant points:

<details>
@sbueringer 
I would probably expect from a user pov that no message prefix is added if message or messageExpression is set

@erikgb 
From a developer POV I think it is nice to get some context automatically injected into the error message. :wink: But I would prefer the invalid value to be echoed, and not the type. So I agree there is a bug somewhere.

@JoelSpeed 
When you add an XValidation, you can specify the type of the error, whether it's Invalid, Forbidden etc, that is where this context is coming from, I wonder if this is specifically an issue with Invalid, or whether the same also applies to Forbidden or other error types

@liggitt 
maybe something like this would work
```diff
diff --git a/staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/schema/cel/validation.go b/staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/schema/cel/validation.go
index 575fd5e2e9a..2a3f7ca29df 100644
--- a/staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/schema/cel/validation.go
+++ b/staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/schema/cel/validation.go
@@ -476,15 +476,16 @@ func (s *Validator) validateExpressions(ctx context.Context, fldPath *field.Path
 						return errs, -1
 					} else {
 						klog.V(2).ErrorS(msgErr, "messageExpression evaluation failed")
-						addErr(fieldErrorForReason(currentFldPath, sts.Type, ruleMessageOrDefault(rule), rule.Reason))
+						addErr(fieldErrorForReason(currentFldPath, obj, ruleMessageOrDefault(rule), rule.Reason))
 						remainingBudget = newRemainingBudget
 					}
 				} else {
-					addErr(fieldErrorForReason(currentFldPath, sts.Type, messageExpression, rule.Reason))
+					// messageExpression is expected to embed the value if desired
+					addErr(fieldErrorForReason(currentFldPath, field.OmitValueType{}, messageExpression, rule.Reason))
 					remainingBudget = newRemainingBudget
 				}
 			} else {
-				addErr(fieldErrorForReason(currentFldPath, sts.Type, ruleMessageOrDefault(rule), rule.Reason))
+				addErr(fieldErrorForReason(currentFldPath, obj, ruleMessageOrDefault(rule), rule.Reason))
 			}
 		}
 	}
@@ -675,7 +676,13 @@ func fieldErrorForReason(fldPath *field.Path, value interface{}, detail string,
 	case apiextensions.FieldValueDuplicate:
 		return field.Duplicate(fldPath, value)
 	default:
-		return field.Invalid(fldPath, value, detail)
+		displayValue := value
+		switch value.(type) {
+		case map[string]any, []any:
+			// avoid outputting complex structured field values
+			displayValue = field.OmitValueType{}
+		}
+		return field.Invalid(fldPath, displayValue, detail)
 	}
 }
```
needs good tests and such
</details>
/sig api-machinery
/cc @liggitt 

### Why is this needed?

Improve UX when CRD implements validation rules using CEL

**Repository:** `kubernetes/kubernetes`
**Base commit:** `03ea6eb2c3e464fae13975fd8d7aed30999f5cac`

## Hints

This issue is currently awaiting triage.

If a SIG or subproject determines this is a relevant issue, they will accept it by applying the `triage/accepted` label and provide further guidance.

The `triage/accepted` label can be added by org members by writing `/triage accepted` in a comment.


<details>

Instructions for interacting with me using PR comments are available [here](https://git.k8s.io/community/contributors/guide/pull-requests.md).  If you have questions or suggestions related to my behavior, please file an issue against the [kubernetes-sigs/prow](https://github.com/kubernetes-sigs/prow/issues/new?title=Prow%20issue:) repository.
</details>

/sig api-machinery
/cc @liggitt

> @sbueringer I would probably expect from a user pov that no message prefix is added if message or messageExpression is set

If `messageExpression` is set, then it's possible for them to include the value in the message text, so maybe omitting the value would make sense.

Even if a static custom `message` is set, I would still expect the invalid value to be injected.

The diff I included in the description would be a good starting point for:
1. switching from including the type to the value
2. avoiding spitting out complex values
3. possibly omit the value when outputting errors from custom messageExpressions
