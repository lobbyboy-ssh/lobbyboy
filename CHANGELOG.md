## Coming Next

- feature: support docker containers now! This is based on
  [footloose](https://github.com/weaveworks/footloose), it can create docker
  containers (or [ignite](https://github.com/weaveworks/ignite)) acting like a
  virtual machine, which can let you ssh to it.

## 0.3.0

- feature: while waiting for providers doing the work for you (like creating a
  new VPS), Lobbyboy will show you the time pass by displaying `.` in terminal,
  then display the total time cost when the operation is done. (by @luxiaba)
- new provider: linode is supported now! (by @luxiaba)
- api change: the provider api is changed, including function name, args,
  returns. Please see the code for details. We will have the official docs soon.
- refactor: the code of lobbyboy is now more readable and elegant now. (also by
  @luxiaba)

## 0.2.3

- chore: Add unit test
- feature: Provider DigitalOcean support choosing region/size/image when
  creating a droplet
- feature: Provider DigitalOcean Dynamic detect new created server's ssh port is
  connectable.

## 0.2.2

Hello world!

This is the initial version of Lobbyboy.
