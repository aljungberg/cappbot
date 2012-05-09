Introduction
------------

CappBot enhances GitHub's issues system by implementing issue lifecycle automation, issue state (new/accepted/fixed), paper trail (the history of label, milestone and assignee changes are posted as comments) and issue voting among other things.

Perform various automation and paper trail functionality on GitHub issues to augment the issues system to better support an open source project.

* For each new issue:
    * Label it as #new.
    * Set the milestone to Someday.
* For every issue:
    * Detect when the labels, milestone or assignee changes and post the new information as a comment. This leaves a "paper trail" so that readers can see *when* things happened. It answers questions like "when was this label added?" or "when was this issue assigned to the current assignee?"
    * Post "what's next" to write in plain language what an issue needs to move forward. Example: "**Milestone:** Someday.  **Label:** #wont-fix.  **What's next?** A reviewer or core team member has decided against acting upon this issue."
    * Detect special syntax in comments to add or remove labels. For example, `+#needs-test` on a line by itself adds the `#needs-test` label, while `-AppKit` would remove the `AppKit` label.
    * If label adding syntax is used, the issue might be automatically opened or closed. E.g. `+#wont-fix` also closes the issue, while `-#fixed` reopens it.
    * Remove labels automatically. If an issue receives the label `#accepted`, CappBot would remove `#needs-test` for instance.
    * Enforce 'state' labels, labels for which only one label can be set at a time, like `#new`, `#accepted`, `#wont-fix`.
    * All of the above features greatly assist when working with Pull requests because labels are usually not visible nor changeable from within a Pull request on github.com.
    * Individuals can be given permission to add or remove labels through the above mechanism without being repository contributors.
    * Track voting: if a user writes +1 or -1 on a line by itself, CappBot records that user's vote and writes the tally of votes in the issue title. E.g. `Reduce load time [+3]`.
    * All of the above is configurable.

Installation
------------

The recommended way to use CappBot is within `virtualenv` (and this is probably the best way to run server side Python software in general.)

    curl -O https://raw.github.com/pypa/virtualenv/master/virtualenv.py
    python virtualenv.py cappbot_env
    . cappbot_env/bin/activate
    pip install -r requirements.txt
    cp main/settings-sample.py settings.py
    # edit settings.py

Usage
-----

See `python main/cappbot.py --help`.

Running the Unit Tests
----------------------

    pip install mock  # an extra requirement only when running the unit tests.
    cd main
    python -m unittest cappbot_test
