import slack_sdk.signature
from aiohttp import web

from . import settings
from .command_ui import CommandUI, CommandResult


class SlackView(web.View):
    async def post(self):
        """自动回复 Slack 消息
        https://api.slack.com/interactivity/slash-commands
        https://api.slack.com/apps
        https://api.slack.com/authentication/verifying-requests-from-slack

        HTTP body 例子: （比如输入：`/weather 94070`）
        > This data will be sent with a `Content-type` header set as `application/x-www-form-urlencoded`.

            token=gIkuvaNzQIHg97ATvDxqgjtO
            &team_id=T0001
            &team_domain=example
            &enterprise_id=E0001
            &enterprise_name=Globular%20Construct%20Inc
            &channel_id=C2147483705
            &channel_name=test
            &user_id=U2147483697
            &user_name=Steve
            &command=/weather
            &text=94070
            &response_url=https://hooks.slack.com/commands/1234/5678
            &trigger_id=13345224609.738474920.8088930838d88f008e0
            &api_app_id=A123456
        """
        request = self.request
        headers = request.headers
        body_bytes = await request.read()
        signature_verifier = slack_sdk.signature.SignatureVerifier(settings.slack_signing_secret)
        if not signature_verifier.is_valid_request(body=body_bytes, headers=headers):
            return web.Response(status=400, text="Invalid request")
        data = await request.post()
        command = data.get("command")
        command_text = data.get("text")

        ui = CommandUI(command=command.strip('/'), command_text=command_text, robot=self.request.app['robot'])
        res = await ui.run()
        if not res:
            return web.Response(text="no result")
        # return web.Response(text=res.slack_result)
        return web.json_response(dict(
            response_type="in_channel",
            text=res.slack_result,
        ))
