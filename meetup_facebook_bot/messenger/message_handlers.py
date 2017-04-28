from meetup_facebook_bot.models.talk import Talk
from meetup_facebook_bot.messenger import messaging
from meetup_facebook_bot.messenger.message_validators import is_talk_rate_command


def handle_talk_info_command(messaging_event, access_token, db_session):
    sender_id = messaging_event['sender']['id']
    payload = messaging_event['postback']['payload']
    talk_id = int(payload.split(' ')[-1])
    talk = db_session.query(Talk).get(talk_id)
    if not talk:
        return
    return messaging.send_talk_info(access_token, sender_id, talk)


def handle_talk_rate_command(messaging_event, access_token, db_session):
    sender_id = messaging_event['sender']['id']
    payload = messaging_event['postback']['payload']
    talks = db_session.query(Talk).all()
    talk_id = int(payload.split(' ')[-1])
    try:
        talk = talks[talk_id - 1]
    except IndexError:
        return
    talk.revert_like(sender_id, db_session)
    return messaging.send_schedule(access_token, sender_id, talks, db_session)


def handle_like_confirmation_command(messaging_event, access_token, db_session):
    raise NotImplemented


def handle_talk_ask_command(messaging_event, access_token, db_session):
    return handle_message_with_sender_id(messaging_event, access_token, db_session)


def handle_message_with_sender_id(messaging_event, access_token, db_session):
    sender_id = messaging_event['sender']['id']
    talks = db_session.query(Talk).all()
    if not is_talk_rate_command(messaging_event):
        return messaging.send_schedule(access_token, sender_id, talks, db_session)
