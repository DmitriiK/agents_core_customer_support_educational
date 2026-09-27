# Prerequisite infrastructure

`prereqs.yaml` is the workshop CloudFormation template for resources the agent uses that are not AgentCore resources. Deploy this stack before `agentcore deploy`.

It creates:

- A Cognito user pool, groups, web and machine clients, resource server, and hosted domain
- `workshop-warranty-check` and `workshop-process-refund` Lambda functions
- SSM parameters under `/app/customersupport/agentcore/` (Cognito IDs and URLs, plus the Lambda ARNs)

The AgentCore CLI stack in `agentcore/cdk/` is generated from `agentcore.json` and does not include this template. Keep the two stacks separate.

Source: [prereqs.yaml](https://ws-assets-prod-iad-r-iad-ed304a55c2ca1aee.s3.us-east-1.amazonaws.com/c770f35f-90a9-4e02-8985-4ef912bddb77/prereqs.yaml)

Lambda handlers live in `lambda-handlers/`. The template points `Code` at those directories. CloudFormation cannot upload a local folder by itself, so package the template first. That zips each handler and rewrites `Code` to an S3 location. Tests live in `lambda-handlers/tests/` and are not part of either zip.

## Deploy

From the repository root, with credentials for the target account. `ARTIFACT_BUCKET` is any S3 bucket in the same region used to hold the Lambda zips.

```bash
aws cloudformation package \
  --template-file infrastructure/prereqs.yaml \
  --s3-bucket "$ARTIFACT_BUCKET" \
  --output-template-file /tmp/agentcore-workshop-prereqs.yaml \
  --region us-east-1

aws cloudformation deploy \
  --stack-name agentcore-workshop-prereqs \
  --template-file /tmp/agentcore-workshop-prereqs.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

`CAPABILITY_NAMED_IAM` is required because the template sets explicit IAM role names.

Run the handler tests:

```bash
python -m unittest discover -s lambda-handlers/tests
```

Check the stack:

```bash
aws cloudformation describe-stacks \
  --stack-name agentcore-workshop-prereqs \
  --region us-east-1 \
  --query 'Stacks[0].StackStatus' \
  --output text
```

## Gateway setup

After the prerequisite stack is deployed, [Lab 3](https://catalog.us-east-1.prod.workshops.aws/workshops/c770f35f-90a9-4e02-8985-4ef912bddb77/en-US/40-lab3-gateway) exposes `workshop-warranty-check` as an MCP tool. The Gateway is not part of `prereqs.yaml`. These commands read the Lambda ARN from SSM and write the gateway plus target into `agentcore.json`. `agentcore deploy` then creates them and injects `AGENTCORE_GATEWAY_MY_GATEWAY_URL` into the CustomerSupport runtime.

The tool schema is `app/CustomerSupport/tool/warranty_schema.json`. Its `inputSchema` is a JSON object with `type: object` directly. A nested `json` wrapper fails deployment.

From the repository root:

```bash
WARRANTY_LAMBDA_ARN=$(aws ssm get-parameter \
  --name /app/customersupport/agentcore/warranty_check_lambda_arn \
  --query 'Parameter.Value' \
  --output text \
  --region us-east-1)

echo "Lambda ARN: $WARRANTY_LAMBDA_ARN"

agentcore add gateway --name my-gateway --runtimes CustomerSupport

agentcore add gateway-target \
  --type lambda-function-arn \
  --name WarrantyCheck \
  --lambda-arn "$WARRANTY_LAMBDA_ARN" \
  --tool-schema-file app/CustomerSupport/tool/warranty_schema.json \
  --gateway my-gateway
```

Expected output:

```text
Added gateway 'my-gateway'
Added gateway target 'WarrantyCheck'
```

Lab 3 leaves the gateway on the default IAM authorizer. [Lab 4](https://catalog.us-east-1.prod.workshops.aws/workshops/c770f35f-90a9-4e02-8985-4ef912bddb77/en-US/50-lab4-deploy) removes `my-gateway` and recreates it as `my-gateway-secure` with the same Cognito JWT authorizer as the runtime. This repository already has that secured gateway in `agentcore.json`. Follow [`auth.md`](../auth.md) for the Cognito values, the gateway replacement, and the authenticated test runs.
