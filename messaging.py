import json

import requests


def send_main_menu_message(access_token, user_id):
    main_menu_message_body = {
            'text': 'Чем могу помочь?',
            'quick_replies': [
                {
                    'content_type': 'text',
                    'title': 'Расписание',
                    'payload': 'schedule payload'
                },
                {
                    'content_type': 'text',
                    'title': 'Вопрос докладчику',
                    'payload': 'question payload'
                },
                {
                    'content_type': 'text',
                    'title': 'Чат',
                    'payload': 'chat payload'
                }
                ]
            }


    main_menu = {
            'recipient': {
                'id': user_id,
                },
            'message': main_menu_message_body,
            }
    return send_message_to_facebook(access_token, main_menu)


def send_message_to_facebook(access_token, message_data):
    headers = {
            'Content-Type': 'application/json',
            }
    params = {
            'access_token': access_token,
            }
    url = 'https://graph.facebook.com/v2.6/me/messages'
    response = requests.post(url, headers=headers, params=params,
                             data=json.dumps(message_data))
    response.raise_for_status()
    return response.json()
