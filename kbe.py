#!/usr/bin/python3

import json
import sys
import os
import subprocess
import tempfile
import typing
from datetime import datetime

conv_name = sys.argv[1]
conv_dir = "./" + conv_name
os.makedirs(conv_dir, exist_ok=True)

pg = 1000


def build_query(
    conv_name: str,
    *,
    method: typing.Literal["read"] | typing.Literal["download"] = "read",
    mid=None,
    file_name: typing.Optional[str] = None,
    pagination_start: typing.Optional[int] = None,
    pagination_size: typing.Optional[int] = None,
) -> str:
    retval = {
        "method": method,
        "params": {
            "options": {
                "channel": {
                    "name": conv_name,
                    "pagination": {},
                },
            },
        },
    }
    if mid is not None:
        retval["params"]["options"]["message_id"] = mid
    if file_name is not None:
        retval["params"]["options"]["output"] = file_name
    if pagination_size is not None:
        retval["params"]["options"]["channel"]["pagination"]["num"] = pagination_size
    if pagination_start is not None:
        retval["params"]["options"]["channel"]["pagination"]["next"] = pagination_start
    return json.dumps(retval)


log_out = conv_dir + "/conv.log"


def run_query(q):
    print(f"Running query: {q!r}\n", file=sys.stderr)
    result = subprocess.run(
        ["keybase", "chat", "api", "-m", q], check=True, capture_output=True
    )
    return json.loads(result.stdout)


def get_content_type(entry):
    return entry["msg"]["content"]["type"]


def get_sender(entry):
    return entry["msg"]["sender"]["username"]


def get_msg_id(entry):
    return entry["msg"]["id"]


def get_filename(entry):
    ctype = get_content_type(entry)
    if ctype == "attachment":
        return entry["msg"]["content"]["attachment"]["object"]["filename"]
    elif ctype == "attachmentuploaded":
        return entry["msg"]["content"]["attachment_uploaded"]["object"]["filename"]
    else:
        print("don't know how to get filename", file=sys.stderr)
        exit(1)


def mk_out_filename(entry):
    return f"{conv_dir}/msg_id_{get_msg_id(entry)}_{get_filename(entry)}"


def outputmsgs(query: str, dest: typing.IO[str]):
    json_data = run_query(query)
    for entry in json_data["result"]["messages"]:
        out = ""
        ctype = get_content_type(entry)
        mid = get_msg_id(entry)
        content = entry["msg"]["content"]
        sent_at = entry["msg"]["sent_at"]
        if ctype == "text":
            out = "<" + get_sender(entry) + "> " + content["text"]["body"]
        elif ctype == "reaction":
            out = "* " + get_sender(entry) + ": " + content["reaction"]["b"]
        elif ctype == "attachment":
            file_name = mk_out_filename(entry)
            out = get_sender(entry) + " sent attachment " + file_name
            if os.path.exists(file_name):
                print(
                    f"already have {file_name!r}, not downloading again",
                    file=sys.stderr,
                )
            else:
                print(f"downloading {file_name!r}", file=sys.stderr)
                run_query(
                    build_query(
                        conv_name, method="download", mid=mid, file_name=file_name
                    )
                )
        elif ctype == "attachmentuploaded":
            out = (
                get_sender(entry)
                + " attachment "
                + mk_out_filename(entry)
                + " uploaded"
            )
        elif ctype == "edit":
            edit = content["edit"]
            out = (
                get_sender(entry)
                + " edited message with id "
                + str(edit["messageID"])
                + " to: "
                + edit["body"]
            )
        elif ctype == "delete":
            out = (
                get_sender(entry)
                + " deleted message with ids "
                + str(content["delete"]["messageIDs"])
            )
        elif ctype == "unfurl":
            out = (
                get_sender(entry)
                + " sent unfurl: "
                + str(content["unfurl"]["unfurl"]["url"])
            )
        else:
            out = "(unknown message type '" + ctype + "')"
        sent_at_str = datetime.utcfromtimestamp(sent_at).strftime("%Y-%m-%d %H:%M:%S")
        dest.write(f"#{mid} - {sent_at_str} - {out}\n\0")
    return json_data["result"]["pagination"].get("next")


print("exporting messages...", file=sys.stderr)

query = build_query(conv_name, pagination_start=0, pagination_size=pg)
last_page = None

with tempfile.TemporaryFile("w+") as tf:
    while next_page := outputmsgs(query, dest=tf):
        if not next_page:
            break
        if next_page == last_page:
            print("received same next pointer twice; halting", file=sys.stderr)
            break
        last_page = next_page
        query = build_query(conv_name, pagination_start=next_page, pagination_size=pg)
    tf.seek(0, 0)
    with open(log_out, "w") as outfile:
        subprocess.run(["tac", "-s", ""], stdin=tf, stdout=outfile, check=True)
