#!/usr/bin/env python3

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import typing
from datetime import datetime

ap = argparse.ArgumentParser()
ap.add_argument("conv_name", help="Conversation name")
ap.add_argument(
    "output_dir",
    nargs="?",
    help="If provided, override the default behavior of naming the output directory after the conversation name",
)
ap.add_argument(
    "--save-json",
    action="store_true",
    default=False,
    help="If set, retain unprocessed API results",
)
ap.add_argument(
    "--skip-attachments",
    action="store_true",
    default=False,
    help="If set, avoid default behavior of retaining all attachments",
)
ap.add_argument(
    "--keep-reverse",
    action="store_true",
    help="If set, store output in original latest-to-oldest order; avoids dependency on the UNIX tac tool",
)
args = ap.parse_args()

conv_name: str = args.conv_name
conv_dir: str = args.output_dir or conv_name.lstrip(".").replace("/", "_")
save_json: bool = args.save_json
skip_attachments: bool = args.skip_attachments
keep_reverse: bool = args.keep_reverse

tac_bin: typing.Optional[str]
if not keep_reverse:
    tac_bin = shutil.which("tac")
    if tac_bin is None:
        ap.error("No tac executable is installed, so --keep-reverse is mandatory")

os.makedirs(conv_dir, exist_ok=True)

pg = 1000


class PaginationOptions(typing.TypedDict):
    num: int
    next: typing.NotRequired[str]  # handle describing starting point


class ChannelOptions(typing.TypedDict):
    name: str


class CommonOptions(typing.TypedDict):
    channel: ChannelOptions


class DownloadOptions(CommonOptions):
    output: str  # filename
    message_id: int


class ReadOptions(CommonOptions):
    pagination: typing.NotRequired[PaginationOptions]


class QueryParams(typing.TypedDict):
    options: DownloadOptions | ReadOptions


class Query(typing.TypedDict):
    method: typing.Literal["read"] | typing.Literal["download"]
    params: QueryParams


def build_query(
    conv_name: str,
    *,
    method: typing.Literal["read"] | typing.Literal["download"] = "read",
    message_id: typing.Optional[int] = None,
    file_name: typing.Optional[str] = None,
    pagination_start: typing.Optional[str] = None,
    pagination_size: typing.Optional[int] = None,
) -> str:
    options: DownloadOptions | ReadOptions
    match method:
        case "read":
            options = ReadOptions(
                channel=ChannelOptions(
                    name=conv_name,
                ),
                pagination=PaginationOptions(
                    num=pagination_size or pg,
                    next=pagination_start or "",
                ),
            )
        case "download":
            assert file_name is not None
            assert message_id is not None
            options = DownloadOptions(
                channel=ChannelOptions(
                    name=conv_name,
                ),
                output=file_name,
                message_id=message_id,
            )
    retval: Query = {
        "method": method,
        "params": {
            "options": options,
        },
    }
    return json.dumps(retval)


log_out = os.path.join(conv_dir, "conv.log")

json_out: typing.Optional[typing.IO[str]] = None
if save_json:
    json_out = open(os.path.join(conv_dir, "conv.json"), "w")


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
        sys.exit(1)


def mk_out_filename(entry):
    return (
        f"{conv_dir}/msg_id_{get_msg_id(entry)}_{get_filename(entry).replace('/', '_')}"
    )


def outputmsgs(query: str, dest: typing.IO[str]):
    json_data = run_query(query)
    if json_out is not None:
        json.dump(json_data, json_out, indent=None)
        json_out.write("\n")
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
            if not skip_attachments:
                if os.path.exists(file_name):
                    print(
                        f"already have {file_name!r}, not downloading again",
                        file=sys.stderr,
                    )
                else:
                    print(f"downloading {file_name!r}", file=sys.stderr)
                    run_query(
                        build_query(
                            conv_name,
                            method="download",
                            message_id=mid,
                            file_name=file_name,
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

query = build_query(conv_name, pagination_size=pg)
last_page = None

with tempfile.NamedTemporaryFile("w+", dir=conv_dir) as tf:
    while next_page := outputmsgs(query, dest=tf):
        if not next_page:
            break
        if next_page == last_page:
            print("received same next pointer twice; halting", file=sys.stderr)
            break
        last_page = next_page
        query = build_query(conv_name, pagination_start=next_page, pagination_size=pg)
    tf.flush()
    tf.seek(0, 0)
    if keep_reverse:
        # use a hardlink so NamedTemporaryFile cleanup still works
        if os.path.exists(log_out):
            os.unlink(log_out)
        os.link(tf.name, log_out)
    else:
        with open(log_out, "w") as outfile:
            subprocess.run(["tac", "-s", ""], stdin=tf, stdout=outfile, check=True)
