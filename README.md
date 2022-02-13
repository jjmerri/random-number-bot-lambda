# random-number-bot-lambda

This is a Reddit bot that responds to mentions on reddit to provide random numbers. It provides random numbers from random.org (rdo). rdo provides an API to request random numbers and gives people the ability to verify that the random number came from rdo in a trusted way.

## Usage

The bot can be used to provide a single random number or multiple random numbers all at once (no repeats). Making a comment on Reddit in the following formats will prompt the bot to reply with random numbers and instructions on how to verify the random number came from rdo.

1 number 1-100:

`/u/yourbotname 100`

3 numbers 1-50:

`/u/yourbotname 3 50` - alternatively `/u/yourbotname 50 3` will also give you 3 numbers between 1 and 50

## Deploying and Running

The bot is deployed as an AWS lambda using [serverless](https://www.serverless.com/framework/docs/providers/aws/cli-reference/deploy). It requires a number of values in the AWS parameter store for each serverless stage you define (e.g. dev, staging, prod). It uses SES to send error emails and also sends Reddit PMs to the defined user.

- rnb-reddit-username-${stage} - the bot's Reddit username
- rnb-reddit-password-${stage} - the bot's Reddit password
- rnb-reddit-client-id-${stage}	- the Reddit app client ID
- rnb-reddit-client-secret-${stage}	- the Reddit app client secret
- rnb-email-server-${stage}	- SES email server
- rnb-email-username-${stage}	- SES username
- rnb-email-password-${stage}	- SES password
- rnb-dev-email-${stage} - email address to receive error emails
- rnb-dev-username-${stage}	- the Reddit username that will receive error PMs
- rnb-rdo-api-key-${stage} - random.org API key that is used to retreive random numbers.
