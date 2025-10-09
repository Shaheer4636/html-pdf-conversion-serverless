Idea: automatically generate the service level agreement report for custom apps.

Using:
1. Synthatic canaries (monitoring the endpoint)
2. S3 buckets for storage of canary output and storage of reports in html
3. Lambda function (data pipeline): this function will process data from s3 bucket of synthatic output and convert it into html report
4. Lambda function (at root .py): this function will convert html to pdf using wkhtml to pdf and other libs. 
