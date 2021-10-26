# Lobbyboy

> What is a lobby boy? A lobby boy is completely invisible, yet always in sight.
> A lobby boy remembers what people hate. A lobby boy anticipates the client's
> needs before the needs are needed. A lobby boy is, above all, discreet to a
> fault.
>
> <p align='right'>--The Grand Budapest Hotel</p>

## What is lobbyboy?

Well, lobbyboy is a ssh server. Yes, like `sshd`. But instead of spawn a new
shell on the server like sshd, when you ssh to lobbyboy, lobbyboy will create a
new server(VPS) from available providers(meaning to say, DigitalOcean, AWS, GCP,
Vultr, etc), then redirect you to the newly created servers. Of course, if
lobbyboy finds any servers available already, he will just ask if you want to
enter the existing server, or still want to create a new one.

```
                                                       create
 +------------------+          +--------------------+  new server  +--------------------------+
 |                  |          |                    |------------->|                          |
 User(You!)         |--ssh----->    lobbyboy        |              |  DigitalOcean            |
 |                  |          |                    |------------->|  (or any other providers |
 +------------------+          +--------------------+     ssh      +--------------------------+
```

## Key Features

- talks in SSH2 protocol, no need to install any software of configs for
  client-side, just ssh to lobbyboy!
- extendable provider: just implement 3 methods, then lobbyboy can work with any
  provider!
- destroy the server when you no longer needed.
- manage ssh keys for you

# Installation

```
   pip install lobbyboy
```
