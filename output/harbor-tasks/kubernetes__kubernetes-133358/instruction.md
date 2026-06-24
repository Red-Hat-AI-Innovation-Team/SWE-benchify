DeleteOptions decode error returns 5xx error
(hoisted from https://github.com/kubernetes/kubernetes/issues/114162)

### What happened?

#### Delete Request error
When constructing a delete request with one or more error parameters, I get a 500 response code and the same error message "converting (v1.APIResourceList) to (v1.DeleteOptions): unknown conversion", which makes it unclear to me which parameter is the error
I found this error in multiple endpoints(my guess is that any operation involving delete will trigger this kind of problem):
`/apis/batch/v1/namespaces/{namespace}/cronjobs`
`/api/v1/persistentvolumes/{name}`
`/apis/node.k8s.io/v1/runtimeclasses`

#### Kubernetes apiVersion/kind mismatch
When a parameter in the request references the API spec "#/definitions/io.k8s.apimachinery.pkg.apis.meta.v1.DeleteOptions" and is passed a parameter type that is different from the template definition. then you will receive 500 code with message "couldn\\'t get version/kind; json parse error: json: cannot unmarshal xxxinto Go struct field xxx of type xxx"
such as the apiVersion paramter type is string,but when I pass a true in it,will receive 500 code
![image](https://user-images.githubusercontent.com/49607803/204244470-c96b4cb6-1b30-44ba-95bb-85a0e9268c94.png)

#### Go type mismatch
When the type of query parameter set in the delete request（`/apis/samplecrd.k8s.io/v1/namespaces/{namespace}/networks`） does not match the type of body parameter，I got 500 code with message：
![image](https://user-images.githubusercontent.com/49607803/204268914-f69036b7-5a47-4972-bb55-606c56e1a6ce.png)


### What did you expect to happen?

#### Delete Request error
I think the response code that should be returned when an error parameter type is passed in is 400(Bad Request)rather than 500

#### Kubernetes apiVersion/kind mismatch
I think the response code that should be returned when an error parameter type is passed in is 400(Bad Request)rather than 500

#### Go type mismatch
I think the response code that should be returned when an error parameter type is passed in is 400(Bad Request)rather than 500

### How can we reproduce it (as minimally and precisely as possible)?

#### Delete Request
passing error value for parameter `dryRun`   `orphanDependents ` and `gracePeriodSeconds`

curl -v -X DELETE 'https://xxxx:6443/apis/node.k8s.io/v1/runtimeclasses?orphanDependents=false&pretty=underlying&limit=76&timeoutSeconds=11&propagationPolicy=schoolcraft' -H 'Authorization:CENSORED' -H 'Accept: */*' -H 'Content-Type: application/json; charset=UTF-8' -d '{ "orphanDependents": true, "dryRun": [ null ], "kind": "APIResourceList", "preconditions": { "uid": "6d2e8f38-82c5-4957-8ca0-fb98605f8417", "resourceVersion": "v1" }, "gracePeriodSeconds": 30, "propagationPolicy": "" }'

curl -v -X DELETE 'https://xxxx:6443/apis/batch/v1/namespaces/periodically/cronjobs/unfaceted?orphanDependents=true&pretty=prematurely&dryRun=abocclusion&gracePeriodSeconds=5819.4694333895295&propagationPolicy=perviousness' -H 'Authorization:CENSORED' -H 'Accept: */*' -H 'Content-Type: application/json; charset=UTF-8' -d '{ "apiVersion": "v1", "gracePeriodSeconds": 30, "kind": "APIResourceList", "orphanDependents": "randomString", "preconditions": { "resourceVersion": "v1" }, "propagationPolicy": "randomString" }

curl -v -X DELETE 'https://xxxx:6443/api/v1/persistentvolumes/{name}?orphanDependents=9499.733908450577' -H 'Authorization:xxx' -H 'Accept: */*' -H 'Content-Type: application/json; charset=UTF-8' -d '{ "apiVersion": "v1", "gracePeriodSeconds": 30, "kind": "APIResourceList", "orphanDependents": "", "preconditions": { "resourceVersion": "v1beta1" } }'

#### Kubernetes apiVersion/kind mismatch
curl -v -X DELETE 'https://xxxx:6443/apis/storage.k8s.io/v1/csinodes?dryRun=All&fieldSelector=&gracePeriodSeconds=1&labelSelector=app=nginx&limit=1&orphanDependents=true&pretty=fuzzstring&propagationPolicy=fuzzstring&resourceVersion=fuzzstring&timeoutSeconds=1' -H 'Authorization:xxx' -H 'Accept: */*' -H 'Content-Type: application/json; charset=UTF-8' -d '{ "apiVersion": false, "gracePeriodSeconds": 30, "kind": "APIResourceList", "orphanDependents": "", "preconditions": { "resourceVersion": "v1beta1" } }'

#### Go type mismatch
curl -v -X DELETE 'https://xxxx:6443/apis/samplecrd.k8s.io/v1/namespaces/{name}/networks/{name}?dryRun=fuzzstring&gracePeriodSeconds=1&orphanDependents=true&pretty=fuzzstring&propagationPolicy=fuzzstring' -H 'Authorization:xxx' -H 'Accept: */*' -H 'Content-Type: application/json; charset=UTF-8' -d '{"propagationPolicy":false}'

**Repository:** `kubernetes/kubernetes`
**Base commit:** `1b0bf0a08043469200edfd27e768af1f26b88fed`

## Hints

@liggitt The issue is exactly the same as mine, and I’ve been wanting to fix it for a while. I’ll go ahead and fix it now.

/assign


/cc

/triage accepted
Thanks @rayowang for taking this one.

/assign
