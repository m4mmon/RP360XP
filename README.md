This is an attempt at re-creating an application for managing the DigiTech RP360XP on Linux and Windows.

For now, with the help of LLMs, I have performed a quite deep analysis of the communication protocol (serial-based, so that's easy to listen).

From Nexus (the official application from DigiTech), I have been able to extract all the supported effects/amps.

[There](serial-mitm), you have the setup and the small scripts I have used to perform the capture of the communication (a Raspberry Pi 4 in gadget mode to act as a man-in-the-middle between the PC and the RP360XP).

[There](protocol), some preliminary notes on the protocol. I'll soon delete that, it's incompleted and outdated.

Finally, [there](src/rp360xp), you have the complete (AFAIK) implementation of a library for interacting with the RP360XP, and a quite complete command-line tool to manage it. It should work on Linux and Windows, but I have only tested it on Linux.


A GUI is in progress. Don't expect something fancy, but something solid, functional, that just works and, hopefully, future-proof. It is Qt-based.

While analyzing the messages exchanged between the official Windows application (Nexus) and the device, some messages were found that Nexus would not use. Not much, but things like some system parameters (foot switch mode, master volume, etc.). These will be integrated to the GUI :)
