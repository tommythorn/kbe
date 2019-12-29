# kbe

kbe is a python script to export [Keybase] chats.

## Usage

Let's assume your keybase username is `zapashcanon` and that you have a chat with someone named `emersion`, to export this chat, you can just:

```sh
./kbe.py zapashcanon,emersion
```

It will create a folder `zapashcanon,emersion` in which you'll find a JSON file containing raw logs, a `.log` file containing human-readable export of the chat. It'll also download all attachments of the chat and put them in that same folder.

## License

See [LICENSE].

[Keybase]: https://keybase.io/
[LICENSE]: ./LICENSE.md
