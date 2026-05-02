## Prepare package 

```
mkdir package
pip install requests -t package/
cp fetch_issues.py query.graphql .token .token_opensearch.prod package/
cd package
zip -r ../function.zip .

Create: 

aws lambda create-function \
  --function-name community-metrics-sync \
  --runtime python3.11 \
  --handler fetch_issues.lambda_handler \
  --zip-file fileb://function.zip


Update:

cd package
rm fetch_issues.py
cp ../fetch_issues.py .
zip -r ../function.zip .
cd ..
aws lambda update-function-code \
  --function-name community-metrics-sync \
  --zip-file fileb://function.zip
```

Create EventBridge (cronjob): 


```
aws events put-rule \
    --schedule-expression "cron(0 7 * * ? *)" \
    --name daily-sync-rule

aws lambda add-permission \
    --function-name community-metrics-sync  \
    --statement-id daily-sync-permission \
    --action 'lambda:InvokeFunction' \
    --principal events.amazonaws.com \
    --source-arn arn:aws:events:us-east-1:478874568403:rule/daily-sync-rule


aws events put-targets \
    --rule daily-sync-rule \
    --targets "Id"="1","Arn"="arn:aws:lambda:us-east-1:478874568403:function:community-metrics-sync"



```