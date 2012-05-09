#! /usr/bin/env python
# -*- coding: utf8 -*-

#
# BSD License
#
# Copyright (c) 2011-12, Alexander Ljungberg
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
     * If label adding syntax is used, the issue might be automatically opened or closed. E.g. `+#wont-fix` also closes the issue, while `-#fixed` reopens it.
     * Remove labels automatically. If an issue receives the label `#accepted`, CappBot would remove `#needs-test` for instance.
     * All of the above features greatly assist when working with Pull requests because labels are usually not visible nor changeable from within a Pull request on github.com.
     * Individuals can be given permission to add or remove labels through the above mechanism without being repository contributors.
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
#   5. post paper trail
#   6. close or reopen the issue if the syntax in 1 triggers such actions.
#
# For determining what is 'new' and what is old, keep a small local database recording the newest change we've
# processed.
#
# We also need to check user permissions so that not just anyone can change issues.

from operator import attrgetter
import argparse
import datetime
import imp
import json
import logbook
import os
import re
import sys
import time

import iso8601

from mini_github3 import GitHub

ADD_LABEL_REGEX = re.compile(r'^\+([-\w\d _#]*[-\w\d_#]+)$|^(#[-\w\d _#]*[-\w\d_#]+)$')
REMOVE_LABEL_REGEX = re.compile(r'^-([-\w\d _#]*[-\w\d_#]+)$')

VOTE_REGEX = re.compile(r'^[-\+][01]$')

TITLE_VOTE_REGEX = re.compile(r' \[[-+]\d+\]$')


def is_issue_new(issue):
    """Return True if an issue hasn't been manually configured before CappBot got to it."""

    return issue.milestone is None and issue.assignee is None and not any(label for label in issue.labels)


class CappBot(object):
    def __init__(self, settings, database, dry_run=False, memorise_forgotten=False):
        self.settings = settings
        self.github = GitHub(api_token=settings.GITHUB_TOKEN)
        self.repo_user, self.repo_name = settings.GITHUB_REPOSITORY.split("/")
        self.database = database
        self.dry_run = dry_run
        self.memorise_forgotten = memorise_forgotten

    def get_current_user(self):
        if not getattr(self, '_current_user', None):
            self._current_user = self.github.current_user()
        return self._current_user
    current_user = property(get_current_user)

    def has_seen_issue(self, issue):
        """Return true if the issue is in our database."""

        db = self.database

        return 'issues' in db and db['issues'].get(unicode(issue.id)) is not None

    def last_seen_issue_update(self, issue):
        """Return the last seen updated_at time in YYYY-MM-DDTHH:MM:SSZ string format.
        Note that updated_at might only change when there is a new comment. It does not
        seem to change when there is a new label.

        """

        if not self.has_seen_issue(issue):
            return None
        return self.database['issues'][unicode(issue.id)].get('updated_at')

    def get_first_run_date(self):
        if not self.database.get('first_run'):
            self.database['first_run'] = datetime.datetime.now().isoformat()
        return iso8601.parse_date(self.database['first_run'])
    first_run_date = property(get_first_run_date)

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
            'assignee_id': int(issue.assignee.id) if issue.assignee else None,
            'labels': sorted(label.name for label in issue.labels),
            'updated_at': issue.updated_at  # (as a string)
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
        """Record the id of the newest comment so we can recognise new comments in the future,
        and the time of the last update so that we can skip

        """

        db = self.database

        db['issues'][unicode(issue.id)]['latest_seen_comment_id'] = issue._comments[-1].id if issue._comments else None

    def get_issue_changes(self, issue):
        """Examine the given issue against what is stored in the database to see how it's been changed, if it has."""

        # Issue must be recorded at this point.
        record = self.database['issues'][unicode(issue.id)]

        r = set()
        if set(record['labels']) != set(label.name for label in issue.labels):
            r.add('labels')

        if record['assignee_id'] != (int(issue.assignee.id) if issue.assignee else None):
            r.add('assignee')

        if record['milestone_number'] != (int(issue.milestone.number) if issue.milestone else None):
            r.add('milestone')

        # _comments might not have been loaded yet in which case we can't detect changes there.
        if hasattr(issue, '_comments') and issue.comments and (record['latest_seen_comment_id'] is None or record['latest_seen_comment_id'] != int(issue._comments[-1].id)):
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
            patch['labels'] = map(unicode, defs['labels'])

        if defs.get('assignee') is not None:
            patch['assignee'] = defs['assignee']

        if len(patch):
            if not self.dry_run:
                try:
                    issue.patch(**patch)
                except:
                    logbook.error(u"Unable to change issue %s with attributes %r" % (issue, patch))
                    raise
            logbook.info(u"Installed defaults %r for issue %s." % (patch, issue))

    def get_new_comments(self, issue):
        """Get all comments which are new since the last call to record_latest_seen_comment."""

        record = self.database['issues'][unicode(issue.id)]
        latest_seen_comment_id = record['latest_seen_comment_id']

        comments = issue._comments

        if latest_seen_comment_id is None:
            return comments

        for n, comment in enumerate(sorted(comments, key=attrgetter('id'))):
            if comment.id == latest_seen_comment_id:
                return comments[n + 1:]
            elif comment.id > latest_seen_comment_id:
                # Assume comment ids always go up, so if the last seen comment has been deleted,
                # we'll react to the next one.
                return comments[n:]

        return []

    def send_message(self, user, subject, body):
        # TODO
        return

        if not user.email:
            logbook.info("No email address found. Unable to send to %s: %s" % (user.login, body))
            return
        logbook.info("Sending message to %s (%s): %s" % (user.login, user.email, body))
        if not self.dry_run:
            # TODO
            pass

    def user_may_alter_labels(self, user):
        return 'labels' in self.settings.PERMISSIONS.get(user.login, ())

    def add_label(self, new_label, labels):
        if new_label in labels:
            # Ensure we move this new label to the end of the list. We need to know which
            # label was added last later.
            labels.remove(new_label)
        labels.append(new_label)
        if new_label in self.settings.CLOSE_ISSUE_WHEN_CAPPBOT_ADDS_LABEL or self.should_open_issue is new_label:
            self.should_open_issue = False
            self.should_close_issue = new_label

    def add_label_due_to_comment(self, new_label, comment, labels):
        if not new_label in self.known_labels:
            logbook.info(u'Ignoring unknown label %s in comment %s by %s.' % (new_label, comment.url, comment.user.login))
            self.send_message(comment.user, u'Unknown label', u'(Your comment)[%s] appears to request that the label `%s` is added to the issue but this does not seems to be a valid label.' % (comment.url, new_label))
            return

        if not self.user_may_alter_labels(comment.user):
            logbook.warning(u"Ignoring unathorised attempt to alter labels by %s through comment %s." % (comment.user.login, comment.url))
            self.send_message(comment.user, u'Unable to alter label', u'(Your comment)[%s] appears to request that the label `%s` is added to the issue but you do not have the required authorisation.' % (comment.url, new_label))
        else:
            logbook.info("Adding label %s due to comment %s by %s" % (new_label, comment.url, comment.user.login))
            self.add_label(new_label, labels)

    def remove_label(self, remove_label, labels):
        if not remove_label in labels:
            return

        labels.remove(remove_label)
        if remove_label in self.settings.OPEN_ISSUE_WHEN_CAPPBOT_REMOVES_LABEL or self.should_close_issue is remove_label:
            self.should_open_issue = remove_label
            self.should_close_issue = False

    def remove_label_due_to_comment(self, remove_label, comment, labels):
        if not remove_label in self.known_labels:
            logbook.info(u'Ignoring unknown label %s in comment %s by %s.' % (remove_label, comment.id, comment.user.login))
            self.send_message(comment.user, u'Unknown label', u'(Your comment)[%s] appears to request that the label `%s` is removed from the issue but this does not seems to be a valid label.' % (comment.url, remove_label))
            return

        if not self.user_may_alter_labels(comment.user):
            logbook.warning(u"Ignoring unathorised attempt to alter labels by %s through comment %s." % (comment.user.login, comment.url))
            self.send_message(comment.user, u'Unable to alter label', u'(Your comment)[%s] appears to request that the label `%s` is removed from the issue but you do not have the required authorisation.' % (comment.url, remove_label))
        else:
            logbook.info("Removing label %s due to comment %s by %s" % (remove_label, comment.id, comment.user.login))
            self.remove_label(remove_label, labels)

    def altered_labels_by_interpreting_new_comments(self, issue, labels):
        new_comments = self.get_new_comments(issue)
        labels = labels[:]

        logbook.debug(u"Examining %d new comment(s) for %s" % (len(new_comments), issue))

        for comment in new_comments:
            if not comment.body:
                continue

            for line in comment.body.split('\n'):
                line = line.strip()

                # Votes look just like +<label> or -<label> where the label is the number 1 or 0.
                if VOTE_REGEX.match(line):
                    continue

                m = ADD_LABEL_REGEX.match(line)
                if m:
                    new_label = (m.group(1) or m.group(2)).lower()
                    self.add_label_due_to_comment(new_label, comment, labels)

                m = REMOVE_LABEL_REGEX.match(line)
                if m:
                    remove_label = m.group(1).lower()
                    self.remove_label_due_to_comment(remove_label, comment, labels)

        return labels

    def altered_labels_per_removal_rules(self, issue, labels):
        for trigger_label, labels_to_remove in self.settings.WHEN_LABEL_REMOVE_LABELS.items():
            if trigger_label in labels:
                for label in labels_to_remove:
                    if label in labels:
                        logbook.info("Removing label %s due to label %s being set." % (label, trigger_label))
                        # This ensures that side effects of removing the label kick in.
                        self.remove_label(label, labels)

        # Remove conflicting labels.
        backwards = list(reversed(labels))
        for n, label in enumerate(backwards):
            if label in self.settings.MUTUALLY_EXCLUSIVE_LABELS:
                for other_label in backwards[n + 1:]:
                    if other_label in self.settings.MUTUALLY_EXCLUSIVE_LABELS:
                        logbook.info("Removing label %s due to label %s being set." % (other_label, label))
                        # This ensures that side effects of removing the label kick in.
                        self.remove_label(other_label, labels)
                # We've removed all conflicting labels at this stage so we're done.
                break

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

    def did_comment_on(self, issue):
        """Return true if we've commented previously on this issue."""

        return issue.comments > 0 and any(comment for comment in issue._comments if comment.user.login == self.current_user.login)

    def ensure_referenced_labels_exist(self):
        """Ensure all labels we might use exist."""

        defs = self.settings.NEW_ISSUE_DEFAULTS
        for label in defs.get('labels', []):
            self.github.Labels.get_or_create_in_repository(self.repo_user, self.repo_name, label)

    def delay_after_update(self):
        """Cause a delay after each paper trail message is posted to limit the maximum rate of
        paper trail messages per minute.

        """

        if self.settings.UPDATE_DELAY:
            time.sleep(self.settings.UPDATE_DELAY)

    def check_prepare_issue(self, issue):
        """Phase 1 issue work: record new issues, install issue defaults, mark déjà vu issues,
        and retrieve the issue comments.

        """

        issue._should_ignore = False
        issue._force_paper_trail = False

        if self.settings.IGNORE_CLOSED_ISSUES_NOT_UPDATED_SINCE_FIRST_RUN and issue.state == 'closed' and iso8601.parse_date(issue.updated_at) < self.first_run_date:
            logbook.debug("Issue %d has been closed since %s, before first run at %s. Ignoring." % (issue.number, issue.updated_at, self.first_run_date.isoformat()))
            issue._should_ignore = True
            return

        if self.has_seen_issue(issue) and self.last_seen_issue_update(issue) == issue.updated_at and not self.get_issue_changes(issue):
            # Note that we need to check both get_issue_changes and updated_at. The updated_at field doesn't update for every
            # change, but it does update for comment changes which is what we need.
            logbook.debug("Issue %d has not changed since last seen update at %s. Ignoring." % (issue.number, issue.updated_at))
            # The important part here is that we don't download the Comments. Downloading all the comments for every
            # issue, on every run, is not very efficient.
            issue._should_ignore = True
            return

        # We'll need this now or later, or both.
        issue._comments = self.github.Comments.by_issue(issue, per_page=100, all_pages=True)

        if self.settings.AVOID_RATE_LIMIT:
            remaining = issue._comments.get_rate_limit_remaining()

            # Remaining will be None if the 'empty comments' optimisation kicked in.
            if not remaining is None:
                delay = 3600.0 / max(1, remaining)
                if delay > 1:
                    logbook.debug("Approaching rate limit (%d requests remaining). Sleeping for %.1fs." % (remaining, delay))
                    time.sleep(delay)

        if self.has_seen_issue(issue):
            # It's not a new issue if we have recorded it previously.
            return

        # Check for comments we've made to this issue previously. Any such comment would indicate
        # there's a problem since we believe !has_seen_issue(issue).
        if self.did_comment_on(issue):
            if self.memorise_forgotten:
                logbook.warning(u"Déjà vu: it looks like CappBot has interacted with %s but it's not in the database. Recording it now." % issue)
                self.record_issue(issue)
                self.recount_votes(issue)
                self.record_latest_seen_comment(issue)
                issue._should_ignore = True
                return

            logbook.warning(u"Déjà vu: it looks like CappBot has interacted with %s but it's not in the database. Ignoring the issue." % issue)
            issue._should_ignore = True
            return

        if is_issue_new(issue):
            logbook.info(u"Issue %s is new." % issue)

            # Assign default labels and milestone.
            self.install_issue_defaults(issue)
        else:
            logbook.info(u"Recording manually triaged %s." % issue)
            # Even if the issue has been manually triaged, we still want to insert a paper trail starting now.
            issue._force_paper_trail = True

        self.record_issue(issue)

    def handle_issue_changes(self, issue):
        if not self.did_comment_on(issue):
            # This issue might not have been changed since we first saw it, but we've never commented
            # on it so there's no paper trail yet.
            issue._force_paper_trail = True

        self.should_close_issue = False
        self.should_open_issue = False

        changes = self.get_issue_changes(issue)

        if not changes:
            # Make sure we capture the update time so we don't need to run the expensive
            # comments check again in the future while this issue remains unchanged.
            if self.last_seen_issue_update(issue) is None:
                self.record_issue(issue)

            logbook.debug(u"No changes for %s" % issue)
            return

        original_labels = [label.name for label in issue.labels]
        new_labels = original_labels[:]

        did_change_votes = False
        if 'comments' in changes:
            # Check for action comments which change labels.
            new_labels = self.altered_labels_by_interpreting_new_comments(issue, new_labels)
            self.record_latest_seen_comment(issue)

            # Count votes.
            did_change_votes = self.recount_votes(issue)

        # Remove labels superseded by new labels.
        new_labels = self.altered_labels_per_removal_rules(issue, new_labels)

        if set(new_labels) != set(original_labels) and not self.dry_run:
            try:
                issue.patch(labels=sorted(map(unicode, new_labels)))
            except:
                logbook.error(u"Unable to set %s labels to %s" % (issue, sorted(map(unicode, new_labels))))
                raise

        # Post paper trail.
        changes = changes.difference(set(['comments']))
        if did_change_votes:
            changes.add('votes')

            # Add the vote count to the issue title.
            issue_title = issue.title
            m = TITLE_VOTE_REGEX.search(issue_title)
            if m:
                issue_title = issue_title[:-len(m.group(0))]
            vote_count = self.get_vote_count(issue)
            if vote_count:
                issue_title += ' [%+d]' % self.get_vote_count(issue)
                logbook.info(u"Recording vote in title of %s: '%s'" % (issue, issue_title))
            elif m:
                logbook.info(u"Clearing vote from title of %s: '%s'" % (issue, issue_title))

            if not self.dry_run:
                try:
                    issue.patch(title=issue_title)
                except:
                    logbook.error(u"Unable to set %is title to %s" % (issue, issue_title))
                    raise

        if new_labels != original_labels:
            changes.add('labels')
        if len(changes):
            # If we're going to reopen the issue, do that before leaving the paper trail.
            if self.should_open_issue and issue.state != 'open':
                logbook.info(u'Reopening %s due to label %s being removed' % (issue, self.should_open_issue))
                if not self.dry_run:
                    try:
                        issue.patch(state="open")
                    except:
                        logbook.error(u"Unable to open %s" % issue)
                        raise

            msg = self.settings.getPaperTrailMessage(issue.assignee.login if issue.assignee else None, issue.milestone.title if issue.milestone else None, new_labels, self.get_vote_count(issue))
            comment = self.github.Comment()
            comment.body = msg
            logbook.info(u"Adding paper trail for %s (changes: %s): '%s'" % (issue, ", ".join(changes), msg))
            if not self.dry_run:
                try:
                    issue._comments.post(comment)
                except:
                    logbook.error(u"Unable to comment on %s" % issue)
                    raise
                self.record_latest_seen_comment(issue)
                self.delay_after_update()

            # Close the issue after leaving the paper trail. It looks more natural.
            if self.should_close_issue and issue.state != 'closed':
                logbook.info(u'Closing %s due to label %s being added' % (issue, self.should_close_issue))
                if not self.dry_run:
                    try:
                        issue.patch(state="closed")
                    except:
                        logbook.error(u"Unable to close %s" % issue)
                        raise

        # Now record the latest labels etc so we don't react to these same changes the next time.
        self.record_issue(issue)

    def run(self):
        logbook.info("Logged in as %s." % self.current_user.login)

        self.ensure_referenced_labels_exist()

        self.known_labels = set(label.name for label in self.github.Labels.by_repository(self.repo_user, self.repo_name, per_page=100, all_pages=True))

        # Everyone who's a collborator automatically has permissions to do everything.
        self.collaborator_logins = set(c.login for c in self.github.Collaborators.by_repository(self.repo_user, self.repo_name, per_page=100, all_pages=True))
        for login in self.collaborator_logins:
            self.settings.PERMISSIONS[login] = ['labels', 'assignee', 'milestone']

        # Find all issues.
        issues = self.github.Issues.by_repository_all(self.repo_user, self.repo_name, per_page=100, all_pages=True)

        logbook.info("Found %d issue(s)." % len(issues))

        # Phase 1: check, prepare and record issues.
        for issue in issues:
            self.check_prepare_issue(issue)

        # Phase 2: react to changed issues.
        for issue in issues:
            if issue._should_ignore:
                continue

            self.handle_issue_changes(issue)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument('--settings', default='settings.py',
        help='settings file to use')
    parser.add_argument('-n', '--dry-run', action='store_true', default=False, dest='dry_run',
        help='only pretend to make changes')
    parser.add_argument('--log', metavar='LOGFILE', type=argparse.FileType('w'), default=sys.stderr,
        help='file to log to (default: stderr)')
    parser.add_argument('-v', '--verbose', action='append_const', const=True,
        help='use verbose logging, use twice for debug logging')
    parser.add_argument('--memorise-forgotten', action='store_true', default=False, dest='memorise_forgotten',
        help='in case of déjà vu, record the issue as fully up to date')

    args = parser.parse_args()

    settings = imp.load_source('settings', args.settings if os.path.exists(args.settings) else os.path.join(os.path.dirname(__file__), 'default_settings.py'))

    if os.path.exists(settings.DATABASE):
        with open(settings.DATABASE, 'rb') as f:
            database = json.load(f)
    else:
        database = {}

    # Write to the database immediately to verify we have write permission and disk space.
    # We don't want to find out that there is a problem at the end and lose all the data.
    if not args.dry_run:
        with open(settings.DATABASE, 'wb') as f:
            json.dump(database, f, indent=2, sort_keys=True)

    log_level = (logbook.WARNING, logbook.INFO, logbook.DEBUG)[min(2, len(args.verbose or []))]
    null_handler = logbook.NullHandler()
    with null_handler.applicationbound():
        with logbook.StreamHandler(args.log, level=log_level, bubble=False) as log_handler:
            with log_handler.applicationbound():
                try:
                    CappBot(settings, database, dry_run=args.dry_run, memorise_forgotten=args.memorise_forgotten).run()
                finally:
                    if not args.dry_run:
                        with open(settings.DATABASE, 'wb') as f:
                            json.dump(database, f, indent=2, sort_keys=True)
