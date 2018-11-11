# Captionary

* Set up a slack bot. You will need:
  * message.channels
  * message.im
  * /caption slash command
* Get the bot OAuth access token and put it into an environment variable named OAUTH_TOKEN
* Run package.py to create a lambda function for the bot
* Create an API gateway for the lambda function, and use that url as the bot event subscription url (as well as the slash command url)
* Invite the bot to a channel

There's a few things I don't automate yet (mostly IAM) listed at the top of package.py
