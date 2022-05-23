### Watcher

watcher.py is a watchdog for your kiln. It is a stand-alone python script that, every few seconds, verifies the kiln-controller.py process is running, and within a certain acceptable temperature range. By default it checks every 10s and after six failed checks, it sends a message to a slack channel. It will send a message every 60s until the problem[s] are solved. It can run on any network, but needs to be able to access the kiln and slack.

Here are the configuration items to potentially set in that script:

| Variable      | Purpose       | Required  | Default |
| ------------- |-------------- | --------- | ------- |
| kiln_url      | the url of the stats api endpoint | Yes | None |
| slack_hook_url| the url of the slack channel to post failures | Yes | None |
| bad_check_limit | send message after this many failures | No | 6 |
| temp_error_limit | consider it a failure if temperature is this far off | No | 10 |
| sleepfor | wait this many seconds between checks | No | 10 |

### Slack

[Slack](https://slack.com/) is a free messaging platform. It is used to send alerts when the watcher finds problems with your kiln.

1. Sign up for a slack account
2. Create a workspace, doesn't matter what you call it
3. Create a channel in that workspace
4. Set up an [incoming web hook](https://slack.com/help/articles/115005265063-Incoming-webhooks-for-Slack) in that channel.
5. Grab the URL for that web hook and use it to set the slack_hook_url in the configuration

If you configured slack, you can test it by starting the watcher without the kiln-controller running and after six failures to reach the kiln, it will send a notification to slack.

I have the slack app on my android phone. This enables me to receive notifications every time I receive a slack message on a specific channel. This way, I can set my phone on vibrate, put it in my pocket and go mow the lawn... yet still know that my kiln is good.

