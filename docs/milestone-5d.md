# Milestone 5D: frontend delivery

Verified offline on 15 October 2026. AWS resources have not been provisioned.

## Implementation

| Component | Configuration |
| --- | --- |
| S3 | Private regional REST origin, AES256, versioning, blocked public access and bucket-owner-enforced ownership |
| OAC | Always sign SigV4; bucket read grant scoped to this distribution ARN |
| CloudFront | Root `index.html`, fresh HTML, cached versioned assets and HTTPS-only uncached API forwarding |
| API forwarding | AWS managed `CachingDisabled` and `AllViewerExceptHostHeader`; cookies, query strings, Origin, CSRF and idempotency preserved |
| DNS/TLS | Existing public Route 53 zone, public A/AAAA aliases, origin ALB alias and separate DNS-validated ACM certificates |
| ALB origin gate | CloudFront prefix list plus exact random token; previous-token overlap supports staged rotation |
| Browser policy | CSP, `nosniff`, frame denial, referrer policy, HSTS and separate API/HTML cache headers |

The origin token is a sensitive input stored in Terraform state/plans and AWS
configuration. Database password values remain outside Terraform. Hosted-zone
ownership and registrar delegation are prerequisites; this root manages records.

## Verification

| Command | Result |
| --- | --- |
| `terraform -chdir=infra/foundation fmt -check -recursive` | Passed |
| `terraform -chdir=infra/foundation validate` | Passed |
| `terraform -chdir=infra/foundation test` | **28 passed**, including 14 frontend-delivery cases |
| `npm --prefix frontend run check-contract` | Backend OpenAPI and generated frontend types match |
| `npm --prefix frontend run build` | Type checking and production build passed |
| `.venv/bin/python -m pytest -q scripts/tests` | **27 passed** |

Mocked tests verify private storage, distribution-scoped read grants, DNS/certificate
wiring, API policies, origin-token agreement and rotation, response headers,
disabled delivery and invalid input/zone names. Tests do not query AWS, issue certificates, publish objects
or exercise CloudFront's runtime behaviour. Backend source and frontend source
are unchanged; the PostgreSQL and browser suites were not rerun in this milestone.

## Remaining integration

CloudFront/S3/OAC authorization, public DNS delegation/propagation, ACM issuance,
end-to-end TLS, token rejection and multi-user browser sessions require deployed
verification. Private-zone lookup behaviour also requires the real provider;
mocked data cannot reproduce that service lookup.

Lambda/SQS event-source mapping, SES deployment, release workflows, public-access
abuse controls and alarms remain pending. Frontend publication is documented;
CI/CD will automate it and serialize releases.

Configuration and commands: [Frontend delivery](frontend-delivery.md).
