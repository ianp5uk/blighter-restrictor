## Improvements
* On the Linux version of parent app, in dark mode, the checkboxes and radio buttons are not very visible, especially when unchecked.
* Launch page - needs a first install page. When the app or an upgrade is applied the app should launch with a badge screen that just says
  "Welcome to Blighter Restrictor v1.X.X" over its badge, i.e., the shield with tick, in small font a very brief copyright notice below the name & version, suggest not too big maybe a 400 x 400 size? This should be displayed for 5 secs only.

## Features
* App should be able to search for users and add them to the list of child or restricted PCs
  So a local, RFC1918 network, scan. Only offer supported PCs and allow parent user to select and add credentials etc. Continue to offer full manual setup. 
* A new "Controls" tab with:
  * Ability to schedule lock time for the child where cannot login - only when non-admin account.
    Must not lock admins out!
    If child is online, should optionally provide 15 min and 5 min warnings then shutdown.