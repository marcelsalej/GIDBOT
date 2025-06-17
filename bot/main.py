"""
Slack Event Listener for AI Dev Bot
- Listens to mentions in Slack
- Sends prompts to the LangChain-based agent
- Replies with AI-generated answers
"""

from fastapi import FastAPI, Request, HTTPException
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.signature import SignatureVerifier
import os
import asyncio # New: For running tasks in the background
import logging # New: For logging events and errors
import re # New: For more robust prompt cleaning

# Assuming 'bot.agents' exists and 'ask_ai_agent' is an async function
# You might need to ensure ask_ai_agent is robust and handles its own errors
from bot.agents import ask_ai_agent

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
    # In a production app, you might want to raise an error or exit
if not SLACK_BOT_TOKEN:
    logger.error("SLACK_BOT_TOKEN environment variable not set.")


# --- Slack Clients ---
client = AsyncWebClient(token=SLACK_BOT_TOKEN)
signature_verifier = SignatureVerifier(SLACK_SIGNING_SECRET)

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

    bot_id = event.get("bot_id") # Get the bot_id from the event itself if available

    logger.info(f"Received event from user {user_id} in channel {channel_id}: '{text}'")

    # Clean prompt: Remove bot mention (e.g., <@U123ABC>)
    # This part needs to be smart: if it's a DM, there's no mention to remove.
    prompt = text
    if bot_id and f"<@{bot_id}>" in prompt: # Only remove if it's a mention and bot_id is in text
        prompt = prompt.replace(f"<@{bot_id}>", "").strip()
    else:
        # Fallback for app_mention if bot_id wasn't immediately found or general cleanup
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
        logger.info(f"Posted thinking message with ts: {thinking_message_ts}")

        # Ask Gemini/AI agent
        
        ai_response = await ask_ai_agent(prompt, user_id=user_id)
        logger.info(f"AI Agent responded to '{prompt}': {ai_response[:100]}...")

        # Update or delete the "thinking" message and post the final response
        if thinking_message_ts:
            await client.chat_update(
                channel=channel_id,
                ts=thinking_message_ts,
                text=ai_response
            )
            logger.info(f"Updated thinking message {thinking_message_ts} with AI response.")
        else:
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=ai_response,
                reply_broadcast=False
            )

    except Exception as e:
        logger.error(f"Error processing AI agent request for user {user_id}, channel {channel_id}: {e}", exc_info=True)
        error_message = f":x: Oops! I encountered an error while trying to process your request: `{e}`"
        
        if thinking_message_ts:
            await client.chat_update(
                channel=channel_id,
                ts=thinking_message_ts,
                text=error_message
            )
        else:
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=error_message,
                reply_broadcast=False
            )

# --- FastAPI Endpoint (Handles both GET and POST) ---
@app.api_route("/", methods=["GET", "POST"]) # <--- REPAIR HERE: Allow both GET and POST
async def slack_events(request: Request):
    """
    Endpoint for Slack Events API and URL verification (GET and POST).
    """
    
    # --- Handle GET request for URL Verification (e.g., Slash Commands, older APIs) ---
    if request.method == "GET":
        print(request.query_params)
        challenge = request.query_params.get("challenge") # Get challenge from query parameters
        if challenge:
            logger.info(f"Received GET URL verification challenge: {challenge}")
            return {"challenge": challenge}
        else:
            logger.error("GET URL verification challenge missing 'challenge' parameter.")
            raise HTTPException(status_code=400, detail="Missing challenge parameter for GET request")

    # --- Handle POST request (Events API, main challenge) ---
    # Important: Get the raw body BEFORE parsing JSON for signature verification
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
    # Crucial for Slack: return 200 OK within 3 seconds, even if processing takes longer.
    
    if body.get("type") == "event_callback":
        event = body.get("event")
        if not event:
            logger.warning("Event callback received without 'event' payload.")
            return {"status": "ok"} 

        event_type = event.get("type")
        
        if event_type == "app_mention":
            asyncio.create_task(process_app_mention_event(event))
            logger.info("App mention event scheduled for background processing.")
        elif event_type == "message" and event.get("channel_type") == "im":
            # Handle direct messages (DM) to the bot
            asyncio.create_task(process_app_mention_event(event)) 
            logger.info(f"Received DM from user {event['user']} in channel {event['channel']}. Scheduled for processing.")
        else:
            logger.info(f"Received unhandled event type: {event_type}. Full event: {event}")

    # Acknowledge all other POST requests (e.g., interactions, commands, unhandled events)
    return {"status": "ok"}


# --- FastAPI Endpoint (Handles both GET and POST) ---
@app.api_route("/slack/events", methods=["GET", "POST"]) # <--- REPAIR HERE: Allow both GET and POST
async def slack_events(request: Request):
    """
    Endpoint for Slack Events API and URL verification (GET and POST).
    """
    
    # --- Handle GET request for URL Verification (e.g., Slash Commands, older APIs) ---
    if request.method == "GET":
        challenge = request.query_params.get("challenge") # Get challenge from query parameters
        if challenge:
            logger.info(f"Received GET URL verification challenge: {challenge}")
            return {"challenge": challenge}
        else:
            logger.error("GET URL verification challenge missing 'challenge' parameter.")
            raise HTTPException(status_code=400, detail="Missing challenge parameter for GET request")

    # --- Handle POST request (Events API, main challenge) ---
    # Important: Get the raw body BEFORE parsing JSON for signature verification
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
    # Crucial for Slack: return 200 OK within 3 seconds, even if processing takes longer.
    
    if body.get("type") == "event_callback":
        event = body.get("event")
        if not event:
            logger.warning("Event callback received without 'event' payload.")
            return {"status": "ok"} 

        event_type = event.get("type")
        
        if event_type == "app_mention":
            asyncio.create_task(process_app_mention_event(event))
            logger.info("App mention event scheduled for background processing.")
        elif event_type == "message" and event.get("channel_type") == "im":
            # Handle direct messages (DM) to the bot
            asyncio.create_task(process_app_mention_event(event)) 
            logger.info(f"Received DM from user {event['user']} in channel {event['channel']}. Scheduled for processing.")
        else:
            logger.info(f"Received unhandled event type: {event_type}. Full event: {event}")

    # Acknowledge all other POST requests (e.g., interactions, commands, unhandled events)
    return {"status": "ok"}

"""
Example Slack Interaction:
User: @dev-bot What's the status of sprint X?
Bot: Sprint X has 12 tickets. 7 completed, 3 in progress, 2 blocked. Top contributors: Alice, Bob.
"""