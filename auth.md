# Cognito authentication

[Lab 4](https://catalog.us-east-1.prod.workshops.aws/workshops/c770f35f-90a9-4e02-8985-4ef912bddb77/en-US/50-lab4-deploy) replaces the default IAM authorizer with a Cognito **custom JWT** authorizer on both the AgentCore Runtime and the Gateway. Callers must send a Cognito access token. The runtime reads the Cognito `username` as the memory actor id and forwards the same `Authorization` header to the gateway.

Deploy the [prerequisite stack](infrastructure/README.md) first. It creates the user pool, the machine client, the web client, and these SSM parameters:

| Parameter | Use |
| --- | --- |
| `/app/customersupport/agentcore/cognito_discovery_url` | OIDC discovery URL for token validation |
| `/app/customersupport/agentcore/client_id` | Machine app client |
| `/app/customersupport/agentcore/web_client_id` | Web app client (user password flow) |
| `/app/customersupport/agentcore/pool_id` | User pool id for admin user commands |

Access tokens from that pool are valid for 60 minutes.

## 1. Read Cognito settings

From the repository root, using the account in `agentcore/aws-targets.json` (`us-east-1`):

```bash
COGNITO_DISCOVERY_URL=$(aws ssm get-parameter \
  --name /app/customersupport/agentcore/cognito_discovery_url \
  --query 'Parameter.Value' --output text --region us-east-1)

COGNITO_CLIENT_ID=$(aws ssm get-parameter \
  --name /app/customersupport/agentcore/client_id \
  --query 'Parameter.Value' --output text --region us-east-1)

COGNITO_POOL_ID=$(aws ssm get-parameter \
  --name /app/customersupport/agentcore/pool_id \
  --query 'Parameter.Value' --output text --region us-east-1)

COGNITO_WEB_CLIENT_ID=$(aws ssm get-parameter \
  --name /app/customersupport/agentcore/web_client_id \
  --query 'Parameter.Value' --output text --region us-east-1)
```

## 2. Secure the runtime

On the `CustomerSupport` runtime in `agentcore/agentcore.json`:

- Allow the `Authorization` header, alongside `X-Amzn-Bedrock-AgentCore-Runtime-Custom-User-Id`.
- Set `authorizerType` to `CUSTOM_JWT`.
- Set `authorizerConfiguration.customJwtAuthorizer.discoveryUrl` to `$COGNITO_DISCOVERY_URL`.
- Set `allowedClients` to the machine client id and the web client id.

`discoveryUrl` is the Cognito OIDC document AgentCore uses to fetch signing keys. `allowedClients` rejects tokens minted for any other app client.

This repository already has that runtime authorizer filled in for the current account.

The agent depends on PyJWT:

```bash
cd app/CustomerSupport
uv add pyjwt
cd ../..
```

`app/CustomerSupport/main.py` decodes the bearer token without verifying the signature (AgentCore already validated it) and uses the `username` claim as the user id. `app/CustomerSupport/mcp_client/client.py` reads `AGENTCORE_GATEWAY_MY_GATEWAY_SECURE_URL` and sends the caller `Authorization` header to the gateway.

Validate and deploy:

```bash
agentcore validate
agentcore deploy -y -v
```

## 3. Secure the gateway

Gateway authorizer settings cannot be changed in place. Remove the Lab 3 gateway, deploy that removal, then create a new gateway with JWT from the start.

```bash
agentcore remove gateway --name my-gateway -y
agentcore deploy -y -v

agentcore add gateway --name my-gateway-secure --runtimes CustomerSupport \
  --authorizer-type CUSTOM_JWT \
  --discovery-url "$COGNITO_DISCOVERY_URL" \
  --allowed-clients "$COGNITO_CLIENT_ID,$COGNITO_WEB_CLIENT_ID"

WARRANTY_LAMBDA_ARN=$(aws ssm get-parameter \
  --name /app/customersupport/agentcore/warranty_check_lambda_arn \
  --query 'Parameter.Value' --output text --region us-east-1)

agentcore add gateway-target \
  --type lambda-function-arn \
  --name WarrantyCheck \
  --lambda-arn "$WARRANTY_LAMBDA_ARN" \
  --tool-schema-file app/CustomerSupport/tool/warranty_schema.json \
  --gateway my-gateway-secure

agentcore validate
agentcore deploy -y -v
```

`--runtimes CustomerSupport` injects `AGENTCORE_GATEWAY_MY_GATEWAY_SECURE_URL` into the runtime. This repository already has `my-gateway-secure` and the `WarrantyCheck` target in `agentcore.json`.

## 4. Test runs

The web client uses `USER_PASSWORD_AUTH`. The machine client is for `client_credentials` and is not used in these tests.

Create a confirmed user, then request an access token:

```bash
aws cognito-idp admin-create-user \
  --user-pool-id "$COGNITO_POOL_ID" \
  --username workshopuser@example.com \
  --temporary-password 'TempPass1!' \
  --user-attributes Name=email,Value=workshopuser@example.com Name=email_verified,Value=true \
  --message-action SUPPRESS \
  --region us-east-1

aws cognito-idp admin-set-user-password \
  --user-pool-id "$COGNITO_POOL_ID" \
  --username workshopuser@example.com \
  --password 'WorkshopPass1!' \
  --permanent \
  --region us-east-1

TOKEN=$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id "$COGNITO_WEB_CLIENT_ID" \
  --auth-parameters USERNAME=workshopuser@example.com,PASSWORD='WorkshopPass1!' \
  --query 'AuthenticationResult.AccessToken' --output text \
  --region us-east-1)
```

If `admin-create-user` reports that the user already exists, skip creation and request a new token. After 60 minutes, run `initiate-auth` again.

**Authenticated runtime call.** Expect a return-policy answer for electronics (30-day window, original packaging, full refund to the original payment method):

```bash
SESSION_3=$(python3 -c 'import uuid; print(uuid.uuid4())')
agentcore invoke "What's the return policy for electronics?" \
  --session-id "$SESSION_3" --bearer-token "$TOKEN" --stream
```

**Rejected call.** The same prompt without a bearer token must fail authentication. The runtime no longer accepts an unsigned request:

```bash
agentcore invoke "What's the return policy for electronics?" \
  --session-id "$SESSION_3" --stream --json
```

**Secured gateway.** Warranty lookup goes through the gateway. Both hops use the same Cognito token. Expect PROD-001, Wireless Headphones, status active, expiration 2027-03-01:

```bash
SESSION_E=$(python3 -c 'import uuid; print(uuid.uuid4())')
agentcore invoke "Check the warranty for PROD-001" \
  --session-id "$SESSION_E" --bearer-token "$TOKEN" --stream
```

**Traffic for observability.** Four turns in one session exercise a local tool, product lookup, the gateway warranty tool, and memory. After a few minutes, the traces show which tools ran and how long each step took:

```bash
SESSION_D=$(python3 -c 'import uuid; print(uuid.uuid4())')

agentcore invoke "What's the return policy for accessories?" \
  --session-id "$SESSION_D" --bearer-token "$TOKEN" --stream

agentcore invoke "Tell me about the USB-C Hub" \
  --session-id "$SESSION_D" --bearer-token "$TOKEN" --stream

agentcore invoke "Check the warranty for PROD-002" \
  --session-id "$SESSION_D" --bearer-token "$TOKEN" --stream

agentcore invoke "Do you remember my name?" \
  --session-id "$SESSION_D" --bearer-token "$TOKEN" --stream
```

Accessories return policy is a 14-day window, original unused packaging, store credit or exchange. PROD-002 is the Smart Watch, warranty active through 2028-01-15. The last turn should use the Cognito username `workshopuser@example.com` from the token.
