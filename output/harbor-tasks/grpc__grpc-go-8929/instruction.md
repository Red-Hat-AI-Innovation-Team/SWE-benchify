Surface response body when receiving an unexpected status code and content-type
### Use case(s) - what problem will this feature solve?

When using a gRPC server through a reverse proxy, the client will sometimes see plaintext or HTML error served by the proxy. Currently, the user of the gRPC client just sees:

```
rpc error: code = Unknown desc = unexpected HTTP status code received from server: 500 (Internal Server Error); transport: received unexpected content-type "text/html"
```

### Proposed Solution

It would be more helpful if the response body was included in the error, for example:

```
rpc error: code = Unknown desc = unexpected HTTP status code received from server: 500 (Internal Server Error); transport: received unexpected content-type "text/html"; response body:
<first N bytes of the response body if printable>
```

### Alternatives Considered

This could also be added to the status details, so that they can be shown like this: https://jbrandhorst.com/post/grpc-errors/#:~:text=In%20order%20to%20extract%20these%20errors%20on%20the%20other%20side

Although of course this requires some more code on the client side, maybe not all users want to see the response body, as especially nginx can serve massive amounts of boilerplate HTML in its errors.

### Additional Context

https://github.com/grpc/grpc-go/issues/1924#issuecomment-469870310 commented:

> Still not returning the raw HTML, however, but I think we should cover that with a separate feature request instead of as part of this bug.

But I can't find that the FR was ever filed.

**Repository:** `grpc/grpc-go`
**Base commit:** `adc97de9521a9f377dab5e911039842dc4de23e5`

## Hints

@drigz I will discuss with team and get back to you

@drigz as per discussion with team we currently don't have bandwidth to work on this with priority. We will keep this issue open and pick up later sometime.

If the content-type header does not specify `application/grpc` we close the stream and only provide data about the http status code received [here](https://github.com/grpc/grpc-go/blob/85240a5b02defe7b653ccba66866b4370c982b6a/internal/transport/http2_client.go#L1537C2-L1558C3) . Including the message body that comes in next data frame is also very useful for debugging we want to read that and display it for debugging purpose. So instead of closing the stream , we want to keep reading data frames  until we get `END_STREAM` or we exceed 1kb length and display that as error message along with error code. 

Java does something similar here : If content-type is not grpc return an [error](https://github.com/grpc/grpc-java/blob/65596ae3a9cdf420d91748e5ad1779ad92e14627/core/src/main/java/io/grpc/internal/Http2ClientStreamTransportState.java#L219) and if it returns an error , we read the next data frames till 1kb or endStream [here](https://github.com/grpc/grpc-java/blob/65596ae3a9cdf420d91748e5ad1779ad92e14627/core/src/main/java/io/grpc/internal/Http2ClientStreamTransportState.java#L131C2-L140C8). 

We want to implement something similar.

May I be assigned to solve this issue? @eshitachandwani
