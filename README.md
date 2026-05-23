This is an attempt at re-creating an application for managing the DigiTech RP360XP.

For now, with the help of LLMs, I have performed a quite deep analysis of the communication protocol (serial-based, so that's easy to listen).

From Nexus (the official application from DigiTech), I have been able to extract all the supported effects/amps.

Now the fun will start:
- the idea is to create a solid library to talk to and interact with the RP360XP.
- once that is working, create an UI to manage that.
- be able to re-use existing rp360b (backups) and rp360p (presets) that have been created from Nexus

If that works, great :) don't expect something beautiful, I want something that just works as flawlessly as possible.

I have no fixed timeframe for this project, but it does not look as it will take much time to have something minimal working.
