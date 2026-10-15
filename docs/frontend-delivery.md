# Frontend delivery

## Configuration

Terraform enables frontend delivery when `frontend` is supplied alongside
`application`. The public Route 53 hosted zone must already exist in the target
account and be authoritative through registrar or parent-zone delegation. Zone
ownership and registrar configuration remain outside this Terraform root.

| Input | Requirement |
| --- | --- |
| `frontend.hosted_zone_id` | Existing public Route 53 zone containing both DNS names |
| `frontend.domain_name` | Public application hostname; lowercase, without a trailing dot |
| `frontend.origin_domain_name` | Distinct hostname for the ALB origin in the same zone |
| `application.public_origin` | Exactly `https://` followed by the frontend hostname |
| `application.origin_certificate_arn` | Omit when frontend delivery is enabled; Terraform provisions the origin certificate |
| `origin_verify_token` | Cryptographically random 32-byte value encoded as 64 lowercase hexadecimal characters; sensitive input |
| `origin_verify_previous_token` | Optional previous token, accepted only during staged rotation |

Application AMI/image inputs and initial capacity settings are described in
[Application hosting](application-hosting.md#configuration). Setting
`frontend = null` omits S3, CloudFront, certificates and DNS records; standalone
application hosting requires an existing origin certificate and the origin token.

Terraform requests separate ACM certificates for the public hostname and ALB
origin, creates their DNS validation records and waits for validation. Both use
`us-east-1`, matching the ALB region and CloudFront certificate requirement.
Existing records and certificates are not adopted or overwritten automatically.
Incorrect zone delegation prevents public DNS validation even when the zone ID
and name checks pass.

## Request routing

| Request | Destination and policy |
| --- | --- |
| Public A/AAAA records | CloudFront distribution |
| `/` and non-asset static files | Regional S3 REST origin with OAC; `index.html` is the default root object; edge caching disabled and browser `no-cache` |
| `/assets/*` | S3; versioned Vite assets may cache for up to one year; no viewer cookies or query strings forwarded |
| `/api` and `/api/*` | HTTPS ALB origin; all methods permitted; caching disabled; browser `no-store` |

Static HTTP requests redirect to HTTPS. API requests require HTTPS rather than
redirecting writes. API forwarding uses AWS managed `CachingDisabled` and
`AllViewerExceptHostHeader`: cookies, query strings, Origin, CSRF and idempotency
headers reach the API. CloudFront replaces the viewer Host with the origin
hostname so origin certificate validation uses the ALB hostname. The configured
browser Origin remains the public frontend hostname.

CloudFront preserves API paths, error bodies and status codes. Error caching TTLs
are zero, with no global error-to-HTML rewrite. The current UI uses one root page;
arbitrary client-side routes are not configured. Missing static files remain
errors. `/docs`, `/redoc` and `/openapi.json` are not public API routes in this
distribution.

Response policies set CSP, `nosniff`, frame denial, same-origin referrer policy
and HSTS. CloudFront uses TLS 1.2 or newer for viewers and TLS 1.2 to the ALB.

References: [managed origin request policies](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-managed-origin-request-policies.html),
[managed cache policies](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-managed-cache-policies.html),
[origin HTTPS](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-https-cloudfront-to-custom-origin.html).

## Origin access

The frontend bucket blocks public access, disables ACLs, enables AES256 encryption
and versioning, and denies non-TLS requests. Its bucket policy grants the
CloudFront service `s3:GetObject` only for this distribution's ARN. OAC signs
requests with SigV4 against the regional REST endpoint; S3 website hosting is
not enabled. The bucket does not permit forced deletion while objects remain.

The ALB security group accepts HTTPS from CloudFront origin-facing addresses.
Its forwarding rule additionally requires `X-LabPass-Origin` to match the
configured token and the API path. Other requests receive the default 404.
CloudFront adds this header to origin requests and overwrites a viewer-supplied
value. The prefix list alone does not identify a particular distribution; the
secret token provides the additional gate.

The token is stored in Terraform state, saved plans and CloudFront/ALB
configuration. `sensitive` redacts normal Terraform output; it does not encrypt
state or remove the value from these services. Supply it through protected
deployment configuration and restrict state, plan and AWS configuration access.
Database password values continue to be created outside Terraform.

For rotation, first supply the old token as `origin_verify_previous_token` and
the new token as `origin_verify_token`. Terraform updates the ALB before
CloudFront, preserving access while distribution configuration propagates.
After the apply completes with CloudFront deployed, apply again with the previous
token removed. Replacing the token without this overlap can interrupt API access.

References: [S3 OAC](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html),
[ALB origin restrictions](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/restrict-access-to-load-balancer.html).

## Frontend publication

Terraform manages infrastructure; frontend objects are release artifacts. After
deployment, retrieve the bucket and distribution metadata:

```bash
terraform -chdir=infra/foundation output -json frontend_delivery
```

Set `LABPASS_FRONTEND_BUCKET` to the output bucket name. From the repository root,
publish hashed assets before updating the HTML entry point:

```bash
npm --prefix frontend ci
npm --prefix frontend run check-contract
npm --prefix frontend run build
aws s3 cp frontend/dist/assets/ \
  "s3://${LABPASS_FRONTEND_BUCKET:?Set the frontend output bucket name}/assets/" \
  --recursive --cache-control 'public,max-age=31536000,immutable' --region us-east-1
aws s3 cp frontend/dist/ "s3://${LABPASS_FRONTEND_BUCKET:?}/" \
  --recursive --exclude 'assets/*' --exclude 'index.html' \
  --cache-control 'no-cache' --region us-east-1
aws s3 cp frontend/dist/index.html "s3://${LABPASS_FRONTEND_BUCKET:?}/index.html" \
  --content-type 'text/html' --cache-control 'no-cache' --region us-east-1
```

Retain old hashed assets for browsers running an earlier release. HTML does not
require an invalidation because edge caching is disabled. Content-type metadata
must match the uploaded files; publication uses the AWS CLI's MIME detection for
assets. Serialize releases so older HTML cannot overwrite a newer deployment.
CI/CD, artifact retention and automated publication remain pending.

## Deployment verification

Verify authoritative DNS and both certificate names; confirm direct anonymous S3
requests fail and the frontend loads through its public hostname. Exercise login,
registration, booking retries and cancellation through CloudFront, including
Origin/CSRF rejection and independent user sessions. Confirm API responses and
errors are not cached, asset responses have the expected MIME/cache headers, and
an unrelated CloudFront distribution cannot bypass the ALB token check.

Offline checks: [Terraform](../infra/README.md#offline-checks).
Real CloudFront/S3/OAC, DNS propagation, certificate issuance and end-to-end TLS
remain unverified until AWS deployment.
