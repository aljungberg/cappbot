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
# * Check for changed issues. For each changed issue:
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

ADD_LABEL_REGEX = re.compile(r'^\+([-\w\d _#]*[-\w\d_#]+)$|^(#[-\w\d _#]*[-\w\d_#]+)$')
REMOVE_LABEL_REGEX = re.compile(r'^-([-\w\d _#]*[-\w\d_#]+)$')

VOTE_REGEX = re.compile(r'^[-\+][01]$')

def is_issue_new(issue):
    """Return True if an issue hasn't been manually configured before CappBot got to it."""

    return issue.milestone is None and issue.assignee is None and not any(label for label in issue.labels)


class CappBot(object):
    def __init__(self, settings, database, dry_run=False):
        self.settings = settings
        self.github = GitHub(api_token=settings.GITHUB_TOKEN)
        self.current_user = self.github.current_user()
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
            'comments_count': int(issue.comments),
            'milestone_number': int(issue.milestone.number) if issue.milestone else None,
            'assignee_id': int(issue.assignee.id) if issue.assignee else None,  # github3 is a little inconsistent ATM.
            'labels': sorted(label.name for label in issue.labels),
        }

        # Note we need to use string keys for our JSON database's sake.
        key = unicode(issue.id)
        if key in db['issues']:
            db['issues'][key].update(db_issue)
        else:
            db_issue['votes'] = None
            db_issue['latest_seen_comment_id'] = None
            db['issues'][key] = db_issue

    def record_latest_seen_comment(self, issue):
        """Record the id of the newest comment so we can recognise new comments in the future."""

        db = self.database

        db['issues'][unicode(issue.id)]['latest_seen_comment_id'] = issue._comments[-1].id if issue._comments else None

    def get_issue_changes(self, issue):
        """Examine the given issue against what is stored in the database to see how it's been changed, if it has."""

        # Issue must be recorded at this point.
        record = self.database['issues'][unicode(issue.id)]

        r = set()
        if record['labels'] != sorted(label.name for label in issue.labels):
            r.add('labels')

        if record['assignee_id'] != (int(issue.assignee.id) if issue.assignee else None):
            r.add('assignee')

        if record['milestone_number'] != (int(issue.milestone.number) if issue.milestone else None):
            r.add('milestone')

        if issue.comments and (record['latest_seen_comment_id'] is None or record['latest_seen_comment_id'] != int(issue._comments[-1].id)):
            r.add('comments')

        if issue._force_paper_trail:
            r.add('new')

        return r

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

    def get_new_comments(self, issue):
        """Get all comments which are new since the last call to record_latest_seen_comment."""

        record = self.database['issues'][unicode(issue.id)]
        latest_seen_comment_id = record['latest_seen_comment_id']

        comments = issue._comments

        if latest_seen_comment_id is None:
            return comments

        for n, comment in enumerate(comments):
            if comment.id == latest_seen_comment_id:
                return comments[n + 1:]

        return []

    def altered_labels_by_interpreting_new_comments(self, issue, labels):
        new_comments = self.get_new_comments(issue)
        labels = labels.copy()

        for comment in new_comments:
            if not comment.body:
                continue

            for line in comment.body.split('\n'):
                line = line.strip()
                m = ADD_LABEL_REGEX.match(line)
                if m:
                    new_label = m.group(1) or m.group(2)
                    if not new_label in labels:
                        logbook.info("Adding label %s due to comment %s by %s" % (new_label, comment.id, comment.user.login))
                        labels.add(new_label)
                m = REMOVE_LABEL_REGEX.match(line)
                if m:
                    remove_label = m.group(1)
                    if remove_label in labels:
                        logbook.info("Removing label %s due to comment %s by %s" % (remove_label, comment.id, comment.user.login))
                        labels.remove(remove_label)
        return labels

    def altered_labels_per_removal_rules(self, issue, labels):
        for trigger_label, labels_to_remove in settings.WHEN_LABEL_REMOVE_LABELS.items():
            if trigger_label in labels:
                updated_labels = labels.difference(set(labels_to_remove))
                if updated_labels != labels:
                    logbook.info("Removed label(s) %s due to label %s being set" % (", ".join(labels.difference(updated_labels)), trigger_label))
                    labels = updated_labels
        return labels

    def recount_votes(self, issue):
        """Search for comments with +1 or -1 on a line by itself, and count the last such line as the commenting
        user's vote. Record the total in the database and return whether it changed since the previous recording.
        The special syntax 0, +0 or -0 is also allowed to reset a previously made vote or to express a non counted
        opinion.

        """

        votes = {}
        for comment in issue._comments:
            if not comment.body:
                continue

            for line in comment.body.split('\n'):
                line = line.strip()

                if VOTE_REGEX.match(line):
                    # If a user votes more than once, the final vote is what will count.
                    votes[comment.user.login] = int(line)

        # Differentiate between a vote of 0 (e.g. +1, -1) and no votes.
        score = sum(votes.values()) if len(votes) else None
        record = self.database['issues'][unicode(issue.id)]
        if score != record['votes']:
            record['votes'] = score
            return True
        return False

    def get_vote_count(self, issue):
        """Return the vote tally for the issue."""

        record = self.database['issues'][unicode(issue.id)]
        return record['votes']

    def run(self):
        github = self.github

        logbook.info("Logged in as %s." % self.current_user.login)

        # Ensure all labels exist.
        defs = self.settings.NEW_ISSUE_DEFAULTS
        for label in defs.get('labels', []):
            self.github.Labels.get_or_create_in_repository(self.repo_user, self.repo_name, label)

        self.known_labels = set(label.name for label in self.github.Labels.by_repository(self.repo_user, self.repo_name))

        # Find all issues.
        issues = github.Issues.by_repository(self.repo_user, self.repo_name)

        logbook.info("Found %d issue(s)." % len(issues))

        for issue in issues:
            issue._should_ignore = False
            issue._force_paper_trail = False

            # We'll need this now or later, or both.
            issue._comments = github.Comments.by_issue(issue)

            if self.has_seen_issue(issue):
                # It's not a new issue if we have recorded it previously.
                continue

            # Check for comments we've made to this issue previously. Any such comment would indicate
            # there's a problem since we believe !has_seen_issue(issue).
            if issue.comments > 0 and any(comment for comment in issue._comments if comment.user.login == self.current_user.login):
                logbook.warning(u"Déjà vu: it looks like CappBot has interacted with %s but it's not in the database. Ignoring the issue." % issue)
                issue._should_ignore = True
                continue

            if is_issue_new(issue):
                logbook.info(u"Issue %s is new." % issue)

                # Assign default labels and milestone.
                self.install_issue_defaults(issue)
            else:
                logbook.info(u"Recording manually triaged issue %d." % issue.id)
                # Even if the issue has been manually triaged, we still want to insert a paper trail starting now.
                issue._force_paper_trail = True

            self.record_issue(issue)

        # Check changed issues.
        for issue in issues:
            if issue._should_ignore:
                continue

            changes = self.get_issue_changes(issue)

            if not changes:
                continue

            original_labels = set(label.name for label in issue.labels)
            new_labels = original_labels.copy()

            did_change_votes = False
            if 'comments' in changes:
                # Check for action comments which change labels.
                new_labels = self.altered_labels_by_interpreting_new_comments(issue, new_labels)
                self.record_latest_seen_comment(issue)

                # Count votes.
                did_change_votes = self.recount_votes(issue)

            # Remove labels superseded by new labels.
            new_labels = self.altered_labels_per_removal_rules(issue, new_labels)

            if new_labels != original_labels and not self.dry_run:
                issue.patch(labels=list(new_labels))

            # Post paper trail.
            changes = changes.difference(set(['comments']))
            if did_change_votes:
                changes.add('votes')
            if new_labels != original_labels:
                changes.add('labels')
            if len(changes):
                msg = settings.getPaperTrailMessage(issue.assignee.login if issue.assignee else None, issue.milestone.title if issue.milestone else None, new_labels, self.get_vote_count(issue))
                comment = github.Comment()
                comment.body = msg
                logbook.info(u"Adding paper trail for %s (changes: %s): '%s'" % (issue, ", ".join(changes), msg))
                if not self.dry_run:
                    issue._comments.post(comment)
                    self.record_latest_seen_comment(issue)

            # Now record the latest labels etc so we don't react to these same changes the next time.
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
