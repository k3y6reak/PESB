#-*- coding: utf-8 -*-
import json
import os
import re
import urllib.request
import requests

from bs4 import BeautifulSoup
from slackclient import SlackClient
from flask import Flask, request, make_response, render_template

app = Flask(__name__)

slack_token = ""
slack_client_id = ""
slack_client_secret = ""
slack_verification = ""
sc = SlackClient(slack_token)

# stackoverflow에서 채택된 답변만 파싱해 딕셔너리로 리턴.
def stackoverflow_parse(errorname):
    url = "https://stackoverflow.com"+ "/search?q=python+" + urllib.parse.quote_plus(errorname.lstrip())
    req = requests.get(url)

    sourcecode = req.text
    soup = BeautifulSoup(sourcecode, "html.parser")

    results = {}
    for div in soup.select("div.search-result"):
        if div.select("div.answered-accepted"):
            link = div.find("a", class_="question-hyperlink").get("href")
            title = div.find("a", class_="question-hyperlink").get("title")
            results[title] = "https://stackoverflow.com"+link


    return results

# docs.python.org에서 에러 이름을 찾아 그 내용만 파싱 후 반환.
def python_docs_parse(errorname):
    url = "https://docs.python.org/3/library/exceptions.html"
    req = urllib.request.Request(url)

    sourcecode = urllib.request.urlopen(url).read()
    soup = BeautifulSoup(sourcecode, "html.parser")

    for exception in soup.find_all("dl", class_="exception"):
        if exception.find_all("dt", id=re.compile(errorname, re.IGNORECASE)):
            return exception.find("p").get_text()
        else:
            return "해당 에러가 존재하지 않습니다."

# json 파일을 열고, 읽는 부분이 많아 하나의 함수로 작성하여 파일 이름만 받아옴.
def open_json_file_read(filename):
    with open(filename, 'rt', encoding="UTF-8") as file:
        json_content = file.read()
        json_dict = json.loads(json_content)
        return json_dict

# 로컬상에 에러가 존재하는지 확인하기 위한 파일 탐색.
def error_name_search(errorname):
    tmp = ""
    for(path, dir, files) in os.walk("./error_list"):
        for full_filename in files:
            filename = os.path.splitext(full_filename)[0]
            if filename == errorname:
                tmp = open_json_file_read("./error_list/" + full_filename)
    if tmp == "":
        return open_json_file_read("./error_list/notfound.json")
    else:
        return tmp

# 파이썬 에러 탐색 함수.
def Error_Search(text):
    # text는 <?????> 입력문자 형태.  해당 문자를 모두 소문자로 변환.
    text = text.lower()
    keywords = []

    #command는 봇의 명령어를 출력.
    if "command" in text:
        command_content = open_json_file_read("./content/command_json.json")
        keywords.append(command_content)
    #errorlist는 지원하는 에러 리스트를 출력.
    elif "errorlist" in text:
        error_content = open_json_file_read("./content/error_list.json")
        keywords.append(error_content)
    #find는 에러를 찾기위한 명령.
    #포맷: find: erroname (공백필요.)
    elif "find" in text:
        words = text.split(" ")
        # 공백기준으로 text내용을 자른 후에도 find가 남아있는 경우. 사용자가 find:errorname으로 입력한 경우.
        if "find" in words[-1]:
            # :를 기준으로 한번 더 자르기.
            tmp = words[-1].split(":")
            local_search = error_name_search(tmp[-1])
            #해당 에러가 존재하는 경우.
            if not "Found" in local_search['title']:
                # error_name_search 함수는 json 형태로 반환됨. text 부분이 slack에서 보여지기 때문에
                # text 부분을 파싱해 붙여주는 부분.
                local_search['text'] += " *공식문서 설명* : " + python_docs_parse(tmp[-1]) + "\n"
                local_search['text'] += "### *스택오버플로우 채택 질문* ###\n"
                # stackoverflow_parse 함수는 딕셔너리 형태로 반환됨.
                for result in stackoverflow_parse(tmp[-1]).items():
                    local_search['text'] += "<" + result[1] + "|" + result[0] + ">\n"
                keywords.append(local_search)
            #해당 에러가 존재하지 않는 경우.
            else:
                keywords.append(local_search)
        else:
            # 사용자가 올바르게 검색한 경우.
            local_search = error_name_search(words[-1])
            if not "Found"  in local_search['title']:
                local_search['text'] += " *공식문서 설명* : " + python_docs_parse(words[-1]) + "\n"
                local_search['text'] += "### *스택오버플로우 채택 질문* ###\n"

                for result in stackoverflow_parse(words[-1]).items():
                    local_search['text'] += "<" + result[1] + "|" + result[0] + ">\n"
                keywords.append(local_search)
            else:
                keywords.append(local_search)
    else:
        # 명령어가 존재하지 않는 경우.
        keywords.append(open_json_file_read("./content/default.json"))

    return (keywords)

# 이벤트 핸들하는 함수
def _event_handler(event_type, slack_event):
    print(slack_event["event"])

    if event_type == "app_mention":
        channel = slack_event["event"]["channel"]
        text = slack_event["event"]["text"]

        keywords = Error_Search(text)
        sc.api_call(
            "chat.postMessage",
            channel=channel,
            attachments=keywords #Josn 형식으로 사용.
        )

        return make_response("App mention message has been sent", 200,)

    # ============= Event Type Not Found! ============= #
    # If the event_type does not have a handler
    message = "You have not added an event handler for the %s" % event_type
    # Return a helpful error message
    return make_response(message, 200, {"X-Slack-No-Retry": 1})

@app.route("/listening", methods=["GET", "POST"])
def hears():
    slack_event = json.loads(request.data)

    if "challenge" in slack_event:
        return make_response(slack_event["challenge"], 200, {"content_type":
                                                             "application/json"
                                                            })

    if slack_verification != slack_event.get("token"):
        message = "Invalid Slack verification token: %s" % (slack_event["token"])
        make_response(message, 403, {"X-Slack-No-Retry": 1})
    
    if "event" in slack_event:
        event_type = slack_event["event"]["type"]
        return _event_handler(event_type, slack_event)

    # If our bot hears things that are not events we've subscribed to,
    # send a quirky but helpful error response
    return make_response("[NO EVENT IN SLACK REQUEST] These are not the droids\
                         you're looking for.", 404, {"X-Slack-No-Retry": 1})

@app.route("/", methods=["GET"])
def index():
    return "<h1>Server is ready.</h1>"

if __name__ == '__main__':
    app.run('localhost', port=5000)
