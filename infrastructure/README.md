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
