import os

import boto3

# Created once per container, outside the handler, so warm invocations reuse it.
# No region or credentials here: Lambda sets AWS_REGION and supplies temporary
# credentials from the execution role automatically.
sqs = boto3.client("sqs")


def lambda_handler(event, context):
    response = sqs.send_message(
        QueueUrl=os.environ["QUEUE_URL"],
        MessageBody="hello from infrapilot-learn-fn",
    )
    return {"message_id": response["MessageId"]}
