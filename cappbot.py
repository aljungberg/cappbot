#! /usr/bin/env python
# -*- coding: utf8 -*-

#
# BSD License
#
# Copyright (c) 2011, Alexander Ljungberg
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

"""

Perform various automation and paper trail functionality on GitHub issues to augment the issues system to better support an open source project.

 * For each new issue:
     * Label it as #new.
     * Set the milestone to Someday.
 * For every issue:
     * Detect when the labels, milestone or assignee changes and post the new information as a comment. This leaves a "paper trail" so that readers can see *when* things happened. It answers questions like "when was this label added?" or "when was this issue assigned to the current assignee?"
     * Detect special syntax in comments to add or remove labels. For example, `+#needs-test` on a line by itself adds the `#needs-test` label, while `-AppKit` would remove the `AppKit` label.
     * Remove labels automatically. If an issue receives the label `#accepted`, CappBot would remove `#needs-test` for instance.
     * All of the above features greatly assist when working with Pull requests because labels are usually not visible nor changeable from within a Pull request on github.com.
     * Track voting: if a user writes +1 or -1 on a line by itself, CappBot records that user's vote and writes the tally of votes in the issue title. E.g. `Reduce load time [+3]`.

"""

# Requirements:
#
#     pip install remoteobjects

# TODO
# In the future, CappBot can be extended to support issue triaging in general:
# * close dead issues (e.g. issue has #needs-patch label but no patch has been added in 6 months)

# Here's the plan:
#
# * Find all new issues. For each:
#   1. if the issue already has a label, consider it manually triaged and just record its state.
#   2. otherwise assign the `#new` label and default milestone.
# * Check the `events` feed to look for changed issues. For each changed issue:
#   1. if a comment has been made, look for label changing syntax and update the labels accordingly. Also look for voting syntax and update votes accordingly (making sure to prevent double voting.)
#   2. if a new label has been added which implies other labels should be removed, remove them.
#   3. if the labels, milestone or assignee has been changed, post a status update comment.
#   4. if the voting tally has changed, add it to the title.
#
# For determining what is 'new' and what is old, keep a small local database recording the newest change we've
# processed.

import argparse
import imp
import json
import logbook
import os
import re

from mini_github3 import GitHub


def is_issue_new(issue):
    """Return True if an issue hasn't been manually configured before CappBot got to it."""

    return issue.milestone is None and issue.assignee is None and not any(label for label in issue.labels)


class CappBot(object):
    def __init__(self, settings, database, dry_run=False):
        self.settings = settings
        self.github = GitHub(api_token=settings.GITHUB_TOKEN)
        self.repo_user, self.repo_name = settings.GITHUB_REPOSITORY.split("/")
        self.database = database
        self.dry_run = dry_run

    def has_seen_issue(self, issue):
        """Return true if the issue is in our database."""

        db = self.database

        return 'issues' in db and db['issues'].get(unicode(issue.id)) is not None

    def record_issue(self, issue):
        """Record the information we need to detect whether an issue has been changed."""

        db = self.database

        if not 'issues' in db:
            db['issues'] = {}

        db_issue = {
            'id': int(issue.id),
            'number': int(issue.number),
            'milestone_number': int(issue.milestone.number) if issue.milestone else None,
            'assignee_id': int(issue.assignee.id) if issue.assignee else None,  # github3 is a little inconsistent ATM.
            'labels': [label.name for label in issue.labels]
        }

        # Note we need to use string keys for our JSON database's sake.
        db['issues'][unicode(issue.id)] = db_issue

    def install_issue_defaults(self, issue):
        """Assign default issue labels, milestone and assignee, if any."""

        defs = self.settings.NEW_ISSUE_DEFAULTS

        patch = {}

        milestone_title = defs.get('milestone')
        if milestone_title:
            milestone = self.github.Milestones.get_or_create_in_repository(self.repo_user, self.repo_name, milestone_title)
            patch['milestone'] = milestone.number

        if defs.get('labels') is not None:
            patch['labels'] = defs['labels']

        if defs.get('assignee') is not None:
            patch['assignee'] = defs['assignee']

        if len(patch):
            if not self.dry_run:
                issue.patch(**patch)
            logbook.info(u"Installed defaults %r for issue %s." % (patch, issue))

    def run(self):
        github = self.github

        # Ensure all labels exist.
        defs = self.settings.NEW_ISSUE_DEFAULTS
        for label in defs.get('labels', []):
            self.github.Labels.get_or_create_in_repository(self.repo_user, self.repo_name, label)

        # Find all issues.
        issues = github.Issues.by_repository(self.repo_user, self.repo_name)

        logbook.info("Found %d issue(s)." % len(issues))

        for issue in issues:
            if self.has_seen_issue(issue):
                # It's not a new issue if we have recorded it previously.
                continue

            if is_issue_new(issue):
                logbook.info(u"Issue %s is new." % issue)

                # Assign default labels and milestone.
                self.install_issue_defaults(issue)
            else:
                logbook.info(u"Recording manually triaged issue %d." % issue.id)

            self.record_issue(issue)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument('--settings', default='settings.py',
        help='Settings file to use')
    parser.add_argument('-n', '--dry-run', action='store_true', default=False, dest='dry_run',
        help='Only pretend to make changes')

    args = parser.parse_args()

    settings = imp.load_source('settings', args.settings)

    if os.path.exists(settings.DATABASE):
        with open(settings.DATABASE, 'rb') as f:
            database = json.load(f)
    else:
        database = {}

    try:
        CappBot(settings, database, dry_run=args.dry_run).run()
    finally:
        if not args.dry_run:
            with open(settings.DATABASE, 'wb') as f:
                json.dump(database, f, indent=2)
