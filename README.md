Introduction
------------

CappBot enhances GitHub's issues system by implementing issue lifecycle automation, issue state (new/accepted/fixed), paper trail (the history of label, milestone and assignee changes are posted as comments) and issue voting among other things.

Perform various automation and paper trail functionality on GitHub issues to augment the issues system to better support an open source project.

* Set defaults for new issues, such as the label `#new` and milestone `Someday`.
* Post changes to labels, milestone or assignee as comments. This leaves a "paper trail" so that readers can see *when* things happened. It answers questions like "when was this label added?" or "when was this issue assigned to the current assignee?"
* Post "what's next" notes to describe what an issue needs to move forward in plain language. Example: "**Milestone:** Someday.  **Label:** #wont-fix.  **What's next?** A reviewer or core team member has decided against acting upon this issue."
* Detect special syntax in comments to add or remove labels. For example, `+#needs-test` on a line by itself adds the `#needs-test` label, while `-AppKit` would remove the `AppKit` label.
* If label adding syntax is used, the issue might be automatically opened or closed. E.g. `+#wont-fix` also closes the issue, while `-#fixed` reopens it.
* Remove labels automatically. If an issue receives the label `#accepted`, CappBot would remove `#needs-test` for instance.
* Detect special syntax in comments to change milestone or assignee. For example, `milestone=1.0` or `assignee=aljungberg` on lines of their own.
* Enforce 'state' labels, labels for which only one label can be set at a time, like `#new`, `#accepted`, `#wont-fix`.
* All of the above features greatly assist when working with Pull requests because labels are usually not visible nor changeable from within a Pull request on github.com.
* Individuals can be given permission to add or remove labels through the above mechanism without being repository contributors.
* Track voting: if a user writes +1 or -1 on a line by itself, CappBot records that user's vote and writes the tally of votes in the issue title. E.g. `Reduce load time [+3]`.
* All of the above is configurable.

Installation
------------

The recommended way to use CappBot is with Docker.

    docker build -t cappbot -f Dockerfile .
    
    cp main/settings-sample.py settings.py
    # edit settings.py

    # Example
    mkdir var    
    docker run --rm  -v $PWD/settings.py:/usr/src/app/settings.py:ro -v $PWD/var/:/var/cappbot cappbot:latest

Running
-------

Ok these instructions are pretty vague but basically it's this, to run in GKE:

    gcloud container builds submit --tag gcr.io/cappuccino-200617/cappbot:0.2.2 .
    
    # ... create a temporary container with the persistent volume mounted and copy settings inside ...
    kubectl create ...something...
    kubectl cp settings.py cappbot-<x>:/var/lib/cappbot/
    # delete it
    
    # Now run the real deal:
    kubectl create kubernetes/cappbot.yaml

    # Apply an update:
    kubectl apply -f kubernetes/cappbot.yaml
    
Usage
-----

See `python main/cappbot.py --help`.

Running the Unit Tests
----------------------

    pip install mock  # an extra requirement only when running the unit tests.
    (cd main && python -m unittest cappbot_test)
