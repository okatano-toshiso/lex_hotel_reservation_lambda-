import json
import os
import logging
import re
from datetime import datetime, timedelta
from openai import OpenAI

logger = logging.getLogger()
logger.setLevel(logging.INFO)
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
client = OpenAI(
    api_key=OPENAI_API_KEY,
)


def parse_relative_date(user_input_text):
    """
    Parses relative date expressions like 'tomorrow', 'day after tomorrow', 'next week', 'next month', 'next year', 'week after next', 'yesterday', 'last week', and 'last month' into actual dates.
    Args:
        user_input_text (str): The user input text.
    Returns:
        str: The parsed date in 'YYYY-MM-DD' format, or None if no relative date expression is found.
    """
    today = datetime.today()
    if user_input_text.lower() == "tomorrow":
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    elif user_input_text.lower() == "day after tomorrow":
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")
    elif user_input_text.lower() == "next week":
        return (today + timedelta(weeks=1)).strftime("%Y-%m-%d")
    elif user_input_text.lower() == "week after next":
        return (today + timedelta(weeks=2)).strftime("%Y-%m-%d")
    elif user_input_text.lower() == "next month":
        next_month = today.replace(day=28) + timedelta(days=4)
        return next_month.replace(day=1).strftime("%Y-%m-%d")
    elif user_input_text.lower() == "next year":
        return today.replace(year=today.year + 1).strftime("%Y-%m-%d")
    elif user_input_text.lower() == "yesterday":
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")
    elif user_input_text.lower() == "last week":
        return (today - timedelta(weeks=1)).strftime("%Y-%m-%d")
    elif user_input_text.lower() == "last month":
        last_month = today.replace(day=1) - timedelta(days=1)
        return last_month.replace(day=1).strftime("%Y-%m-%d")
    return None


def parse_date_without_year(check_in_date):
    """
    Parses date expressions without a year into the closest future date.
    Args:
        user_input_text (str): The user input text.
    Returns:
        str: The parsed date in 'YYYY-MM-DD' format, or None if the input is not a valid date.
    """
    today = datetime.today()
    try:
        date_without_year = datetime.strptime(check_in_date, "%m-%d")
        date_with_current_year = date_without_year.replace(year=today.year)
        if date_with_current_year < today:
            date_with_current_year = date_with_current_year.replace(year=today.year + 1)
        else:
            date_with_current_year = date_with_current_year.replace(year=today.year)
        return date_with_current_year.strftime("%Y-%m-%d")
    except ValueError:
        return None


def parse_special_event(user_input_text):
    """
    Parses special event expressions like 'Christmas', 'New Year', 'Halloween', 'Valentine's Day', 'Thanksgiving', and 'Independence Day' into actual dates.
    """
    system_content = "{}のメッセージがイベント日時を取得するのに有効な日付だった場合、mm-ddのDate形式でレスポンスする。有効ではないメッセージだった場合は、Noneを返す。レスポンスの形式はmm-ddかNoneかどちらかです。".format(
        user_input_text
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        temperature=0,
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_input_text},
        ],
    )
    result = response.choices[0].message.content
    if result == "None":
        return None
    else:
        return result


def response_elicit_session(intent_name, slots, slot_to_elicit, message=None):
    dialog_action = {
        "type": "ElicitSlot",
        "slotToElicit": slot_to_elicit,
    }
    if message:
        dialog_action["message"] = {"contentType": "PlainText", "content": message}
    return {
        "sessionState": {
            "dialogAction": dialog_action,
            "intent": {"name": intent_name, "slots": slots, "state": "InProgress"},
        }
    }


def response_close_session(message, intent_name, slots):
    return {
        "sessionState": {
            "dialogAction": {
                "type": "Close",
                "fulfillmentState": "Fulfilled",
                "message": {"contentType": "PlainText", "content": message},
            },
            "intent": {
                "name": intent_name,
                "slots": slots,
                "state": "Fulfilled",
            },
        }
    }


def response_invalid_date_session(
    intent_name, slots, invalid_attempts, slotToElicit, message
):
    return {
        "sessionState": {
            "sessionAttributes": {"invalidAttempts": str(invalid_attempts)},
            "dialogAction": {
                "type": "ElicitSlot",
                "slotToElicit": slotToElicit,
            },
            "intent": {
                "confirmationState": "Denied",
                "name": intent_name,
                "slots": {"CheckInDate": None},
                "state": "InProgress",
            },
        },
        "messages": [
            {
                "contentType": "PlainText",
                "content": message,
            }
        ],
    }


def process_check_in_date(event):  # noqa: F811
    session_state = event.get("sessionState", {})
    intent = session_state.get("intent", {})
    intent_name = intent.get("name", "")
    slots = intent.get("slots", {})
    user_input_text = event.get("inputTranscript", "")

    if event.get("invocationSource") == "DialogCodeHook":
        check_in_date = None
        if slots:
            check_in_date_slot = slots.get("CheckInDate", {})
            if check_in_date_slot:
                check_in_date_value = check_in_date_slot.get("value", {})
                if check_in_date_value:
                    check_in_date = check_in_date_value.get("interpretedValue", None)

        if not check_in_date and isinstance(user_input_text, str):
            relative_date = parse_relative_date(user_input_text)
            if relative_date:
                check_in_date = relative_date
            else:
                check_in_date = parse_special_event(user_input_text)
                if check_in_date:
                    try:
                        datetime.strptime(check_in_date, "%m-%d")
                        check_in_date = parse_date_without_year(check_in_date)
                    except ValueError:
                        return response_elicit_session(
                            intent_name,
                            slots,
                            "CheckInDate",
                            "Please provide a valid check-in date.",
                        )
                else:
                    session_attributes = event.get("sessionState", {}).get(
                        "sessionAttributes", {}
                    )
                    invalid_attempts = int(
                        session_attributes.get("invalidAttempts", "0")
                    )
                    invalid_attempts += 1
                    if invalid_attempts >= 5:
                        return response_close_session(
                            "入力が繰り返し無効です。セッションを終了します。",
                            intent_name,
                            slots,
                        )
                    else:
                        return response_invalid_date_session(
                            intent_name,
                            slots,
                            invalid_attempts,
                            "CheckInDate",
                            "入力された日付が無効です。正しい日付を入力してください。例: 2024-12-25",
                        )
            if check_in_date:
                slots["CheckInDate"] = {"value": {"interpretedValue": check_in_date}}
            else:
                return
        print("check_in_date_fixed", check_in_date)

        response = response_elicit_session(intent_name, slots, "CheckInDate")
    else:
        return response_close_session(
            "Thank you for your information.", intent_name, slots
        )
    return response