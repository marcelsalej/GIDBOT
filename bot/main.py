# bot/main.py

"""
Slack Event Listener for AI Dev Bot
- Listens to mentions in Slack
- Sends prompts to the LangChain-based agent
- Replies with AI-generated answers
"""
import os
import asyncio
import logging
import re
from fastapi import FastAPI, Request, HTTPException
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.signature import SignatureVerifier
from slack_sdk.errors import SlackApiError # Import SlackApiError for specific error handling

# New imports for Jira preloading
from bot.jira_tool_client import JiraTool
from bot.vector_store import index_jira_issues

# Use bot.rag_agent for RAG capabilities as it's currently aliased and used.
from bot.rag_agent import ask_ai_rag as ask_ai_agent

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI()

# --- Configuration ---
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")

# Validate environment variables early
if not SLACK_SIGNING_SECRET:
    logger.error("SLACK_SIGNING_SECRET environment variable not set.")
if not SLACK_BOT_TOKEN:
    logger.error("SLACK_BOT_TOKEN environment variable not set.")


# --- Slack Clients ---
client = AsyncWebClient(token=SLACK_BOT_TOKEN)
signature_verifier = SignatureVerifier(SLACK_SIGNING_SECRET)

# Global variable to store bot_user_id and JiraTool instance
bot_user_id = None
jira_tool_instance = None

@app.on_event("startup")
async def startup_event():
    """
    On startup, fetch the bot's user ID and preload/index Jira data.
    """
    global bot_user_id
    global jira_tool_instance

    try:
        auth_test_response = await client.auth_test()
        bot_user_id = auth_test_response["user_id"]
        logger.info(f"Bot user ID fetched successfully: {bot_user_id}")
    except Exception as e:
        logger.error(f"Failed to fetch bot user ID during startup: {e}", exc_info=True)

    # --- Jira Preloading ---
    try:
        jira_tool_instance = JiraTool()
        jql_query = 'project IN (TRIAGE, "ID", "WL", "MS")'
        logger.info("[STARTUP] Fetching Jira issues for preloading...")
        jira_issues = jira_tool_instance.fetch_jira_issues(jql_query)
        logger.info(f"[STARTUP] Indexing {len(jira_issues)} Jira issues...")
        index_jira_issues(jira_issues)
        logger.info("[STARTUP] Jira issues preloaded and indexed successfully.")
    except Exception as e:
        logger.error(f"[STARTUP] Failed to preload/index Jira issues: {e}", exc_info=True)

# --- Helper Function for Background Processing ---
async def process_app_mention_event(event: dict):
    """
    Handles the logic for an app_mention or DM event in the background.
    """
    user_id = event["user"]
    channel_id = event["channel"]
    text = event["text"]

    # Determine the thread to reply to
    thread_ts = event.get("thread_ts", event["ts"])

    # Get the bot_id from the event first, or use the globally stored one
    current_bot_id = event.get("bot_id", bot_user_id)

    logger.info(f"Received event from user {user_id} in channel {channel_id}: '{text}'")

    # Clean prompt: Remove bot mention (e.g., <@U123ABC>)
    prompt = text
    if current_bot_id and f"<@{current_bot_id}>" in prompt:
        prompt = prompt.replace(f"<@{current_bot_id}>", "").strip()
    else:
        # This regex targets any user/bot mention tag
        prompt = re.sub(r'<@[A-Z0-9]+>', '', prompt).strip()

    if not prompt:
        logger.warning(f"Empty prompt after cleaning for user {user_id} in channel {channel_id}.")
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="It looks like you didn't ask me anything. Please try again with a question!",
            reply_broadcast=False
        )
        return

    # Add a "thinking" indicator
    thinking_message_ts = None
    try:
        thinking_response = await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=":hourglass_flowing_sand: Thinking...",
            reply_broadcast=False
        )
        thinking_message_ts = thinking_response["ts"]
        logger.info(f"Posted thinking message with ts: {thinking_message_ts} and prompt {prompt}")

        # Ask Gemini/AI agent
        ai_response = ""
        try:
            ai_response = await asyncio.wait_for(ask_ai_agent(prompt, user_id=user_id), timeout=120)
        except asyncio.TimeoutError:
            logger.error("AI agent timed out.")
            ai_response = "⚠️ Sorry, I'm taking too long to think. Try again in a bit."
        except Exception as e:
            logger.exception(f"Error from AI agent: {e}")
            ai_response = f"⚠️ Oops, something went wrong: `{e}`"

        # Update or delete the "thinking" message and post the final response
        if thinking_message_ts:
            try:
                update_response = await client.chat_update(
                    channel=channel_id,
                    ts=thinking_message_ts,
                    text=ai_response
                )
                # Check for 'ok: false' in the Slack API response despite 200 status
                if not update_response.get("ok"):
                    error_slack_api = update_response.get("error", "Unknown Slack API error")
                    logger.error(f"Slack chat.update failed (ok: false): {error_slack_api} for channel {channel_id}, ts {thinking_message_ts}")
                    # Fallback: post a new message if update fails
                    await client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=thread_ts,
                        text=f"⚠️ Failed to update previous message. Here's the full response: {ai_response}",
                        reply_broadcast=False
                    )
                else:
                    logger.info(f"Updated thinking message {thinking_message_ts} with AI response.")
            except SlackApiError as e:
                # Catch specific Slack API errors for better debugging
                logger.error(f"Slack API error during chat.update: {e.response['error']} (Code: {e.response.get('response_metadata')}) for channel {channel_id}, ts {thinking_message_ts}", exc_info=True)
                # Fallback: post a new message if update fails
                await client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=f"⚠️ An API error occurred while updating my response. Here's what I got: {ai_response}",
                    reply_broadcast=False
                )
            except Exception as e:
                # Catch any other unexpected exceptions during chat.update
                logger.error(f"Unexpected error during chat.update: {e}", exc_info=True)
                await client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=f"⚠️ An unexpected error occurred while updating my response. Here's what I got: {ai_response}",
                    reply_broadcast=False
                )
        else:
            # If thinking message was never posted, just post the final response
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=ai_response,
                reply_broadcast=False
            )

    except Exception as e:
        logger.error(f"Error processing AI agent request for user {user_id}, channel {channel_id}: {e}", exc_info=True)
        error_message = f":x: Oops! I encountered an error while trying to process your request: `{e}`"
        
        # Try to update the thinking message with an error, or post a new one
        if thinking_message_ts:
            try:
                await client.chat_update(
                    channel=channel_id,
                    ts=thinking_message_ts,
                    text=error_message
                )
            except Exception:
                # If even updating the error fails, post a new error message
                await client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=error_message,
                    reply_broadcast=False
                )
        else:
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=error_message,
                reply_broadcast=False
            )

# --- FastAPI Endpoint (Handles both GET and POST) ---
@app.api_route("/", methods=["GET", "POST"])
async def slack_events_root(request: Request):
    """
    Endpoint for Slack Events API and URL verification (GET and POST).
    Consolidated logic for all Slack event handling.
    """
    
    # --- Handle GET request for URL Verification ---
    if request.method == "GET":
        challenge = request.query_params.get("challenge")
        if challenge:
            logger.info(f"Received GET URL verification challenge: {challenge}")
            return {"challenge": challenge}
        else:
            logger.error("GET URL verification challenge missing 'challenge' parameter.")
            raise HTTPException(status_code=400, detail="Missing challenge parameter for GET request")

    # --- Handle POST request (Events API, main challenge) ---
    raw_body = await request.body()
    
    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse request body as JSON for POST request: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    logger.debug(f"Received Slack POST event: {body}")

    # ✅ Respond to Slack's POST challenge request (Events API)
    if body.get("type") == "url_verification":
        logger.info("Received POST URL verification challenge.")
        challenge_value = body.get("challenge")
        if challenge_value:
            return {"challenge": challenge_value}
        else:
            logger.error("POST URL verification challenge missing 'challenge' parameter.")
            raise HTTPException(status_code=400, detail="Missing challenge parameter")

    # --- Signature verification (for POST requests that are not URL verification) ---
    if not signature_verifier.is_valid_request(raw_body.decode('utf-8'), request.headers):
        logger.warning("Signature verification failed for incoming Slack POST request.")
        raise HTTPException(status_code=403, detail="Invalid Slack signature")

    # --- Immediate Acknowledgment for Event Callbacks ---
    if body.get("type") == "event_callback":
        event = body.get("event")
        if not event:
            logger.warning("Event callback received without 'event' payload.")
            return {"status": "ok"} 

        event_type = event.get("type")
        
        # Handle app_mention events and direct messages to the bot
        if event_type == "app_mention" or (event_type == "message" and event.get("channel_type") == "im"):
            asyncio.create_task(process_app_mention_event(event))
            logger.info(f"Event type '{event_type}' scheduled for background processing.")
        else:
            logger.info(f"Received unhandled event type: {event_type}. Full event: {event}")

    return {"status": "ok"}