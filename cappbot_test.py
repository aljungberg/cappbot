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

from mock import Mock, call
import imp
import json
import logbook
import os
import unittest

from cappbot import CappBot
import mini_github3


def first(iterable):
    try:
        return next(iterable)
    except StopIteration:
        return None


def load_fixture(name):
    with open(os.path.join(os.path.dirname(__file__), 'test_fixtures', name), 'rb') as inf:
        return json.load(inf)


class TestCappBot(unittest.TestCase):
    def setUp(self):
        self.log_handler = logbook.TestHandler()
        self.log_handler.push_thread()

        self.settings = imp.load_source('settings', 'default_settings.py')
        self.settings.GITHUB_REPOSITORY = "alice_tester/blox"
        self.settings.PERMISSIONS['bob'] = ['labels']
        self.database = {}
        self.cappbot = CappBot(self.settings, self.database)
        # Replace the GitHub API with a mock.
        self.cappbot.github = Mock(spec=self.cappbot.github)

        user_template = {'public_repos': 0, 'public_gists': 0, 'name': 'CappBot', 'bio': None, 'url': 'https://api.github.com/users/cappbot', 'type': 'User', 'created_at': '2011-09-02T16:59:16Z', 'html_url': 'https://github.com/cappbot', 'email': None, 'blog': 'www.cappuccino.org', 'avatar_url': 'https://secure.gravatar.com/avatar/44790460d2e62628fc354296057f2b61?d=https://a248.e.akamai.net/assets.github.com%2Fimages%2Fgravatars%2Fgravatar-140.png', 'followers': 0, 'location': 'Villa Straylight', 'gravatar_id': '44790460d2e62628fc354296057f2b61', 'following': 0, 'login': 'cappbot', 'hireable': False, 'company': None, 'id': 1022439}

        self.cappbot_user = mini_github3.User.from_dict(user_template)

        user_template = user_template.copy()
        user_template['name'] = 'Alice Tester'
        user_template['url'] = 'https://api.github.com/users/alice_tester'
        user_template['login'] = 'alice_tester'
        self.alice_user = mini_github3.User.from_dict(user_template)

        user_template = user_template.copy()
        user_template['name'] = 'Bob Tester'
        user_template['url'] = 'https://api.github.com/users/bob_tester'
        user_template['login'] = 'bob'
        self.bob_user = mini_github3.User.from_dict(user_template)

        user_template = user_template.copy()
        user_template['name'] = 'Chuck Tester'
        user_template['url'] = 'https://api.github.com/users/chuck_tester'
        user_template['login'] = 'chuck'
        self.chuck_user = mini_github3.User.from_dict(user_template)

        self.cappbot.github.current_user = Mock(return_value=self.cappbot_user)

    def tearDown(self):
        self.log_handler.pop_thread()

    def test_ensure_referenced_labels_exist(self):
        self.cappbot.ensure_referenced_labels_exist()
        self.cappbot.github.Labels.get_or_create_in_repository.assert_called_with("alice_tester", "blox", "#new")

    def test_current_user(self):
        current_user = self.cappbot.current_user
        self.cappbot.github.current_user.assert_called_once_with()
        self.assertEquals(current_user, self.cappbot_user)

    def configure_github_mock(self, issues, labels, milestones, comments=None):
        """Configure the GitHub API mock to make certain data available.

        The parameters should be arrays of dicts from the JSON fixtures.
        Comments should be an arrays of arrays of dicts.
        """

        # There's quite a bit of GitHub interaction to fake.

        comments = comments or []
        issues = mini_github3.Issues.from_dict(issues)
        labels = mini_github3.Labels.from_dict(labels)
        milestones = mini_github3.Milestones.from_dict(milestones)
        collaborators = mini_github3.Collaborators.from_dict([{'login': login} for login in (self.cappbot_user.login, self.alice_user.login)])

        self.cappbot.github.Collaborators.by_repository = Mock(return_value=collaborators)
        self.cappbot.github.Labels.by_repository = Mock(return_value=labels)

        def install_issue_mock_patch(issue):
            def mock_patch(*args, **kwargs):
                for k, v in kwargs.items():
                    # When you patch a milestone in GitHub V3 you send a numeric id but receive back a full
                    # milestone object.
                    if k == 'milestone':
                        new_v = first(milestone for milestone in milestones if milestone.number == v)
                        if not new_v:
                            raise Exception("mock patch: no such milestone %s" % v)
                        v = new_v

                    # Similar when you patch the labels you send an array of strings but receive back an
                    # array of Label resources.
                    if k == 'labels':
                        new_v = [first(label for label in labels if label.name == aName) for aName in v]
                        if any(not label for label in new_v):
                            raise Exception("mock patch: no such label(s) in %s" % v)
                        v = new_v
                    setattr(issue, k, v)
            issue.patch = Mock(side_effect=mock_patch)

        map(install_issue_mock_patch, issues)

        def install_list_post_patch(a_list):
            def mock_post(a_new_entry):
                a_list.entries.append(a_new_entry)
            a_list.post = Mock(side_effect=mock_post)
        install_list_post_patch(issues)
        install_list_post_patch(milestones)
        install_list_post_patch(labels)

        def milestone_get_or_create_in_repository(user_name, repo_name, milestone_title):
            for milestone in milestones:
                if milestone.title == milestone_title:
                    return milestone

            milestone = mini_github3.Milestone()
            milestone.title = milestone_title
            milestones.post(milestone)  # Will call the Mock version.

            return milestone

        self.cappbot.github.Milestones.get_or_create_in_repository = Mock(side_effect=milestone_get_or_create_in_repository)

        self.cappbot.github.Issues.by_repository = Mock(return_value=issues)
        self.cappbot.github.Issues.by_repository_all = Mock(return_value=issues)

        for n, issue in enumerate(issues):
            issue._mock_comments = mini_github3.Comments.from_dict(comments[n]) if n < len(comments) else mini_github3.Comments(entries=[])
            issue.comments = len(issue._mock_comments)
            install_list_post_patch(issue._mock_comments)

        def get_comments(issue, **kwargs):
            return issue._mock_comments

        self.cappbot.github.Comments.by_issue = Mock(side_effect=get_comments)

        return issues, labels, milestones

    def test_install_defaults(self):
        issues, labels, milestones = self.configure_github_mock(load_fixture('issues.json')[7:8], load_fixture('labels.json'), [load_fixture('milestone.json')])

        self.cappbot.run()

        issues[0].patch.assert_called_with(labels=['#new'], milestone=2)
        self.assertEquals(issues[0]._mock_comments[-1].body, "**Milestone:** Someday.  **Label:** #new.  **What's next?** A reviewer should examine this issue.")
        issues[0]._mock_comments.post.assert_called_with(issues[0]._mock_comments[-1])

    def fake_comment(self, owner, body):
        number = getattr(self, 'fake_comment_number', 5207158) + 1
        self.fake_comment_number = number
        # Date doesn't increase with new comments which maybe isn't entirel realistic.
        return {'body': body, 'url': 'https://api.github.com/repos/alice_tester/blox/issues/comments/%d' % number, 'created_at': '2012-04-18T19:54:40Z', 'updated_at': '2012-04-18T19:54:40Z', 'user': owner.to_dict(), 'id': number}

    def test_ignore_deja_vu(self):
        cappbot_comment = [self.fake_comment(self.cappbot_user, 'Hello.')]

        issues, labels, milestones = self.configure_github_mock(load_fixture('issues.json')[7:8], load_fixture('labels.json'), [load_fixture('milestone.json')], [cappbot_comment])

        self.cappbot.run()

        # No new comment should have been posted.
        self.assertTrue(any(u'Déjà vu: it looks like CappBot has interacted with' in record for record in self.log_handler.formatted_records))
        self.assertEquals([c.body for c in issues[0]._mock_comments], ['Hello.'])

    def test_action_by_comment_label(self):
        issues, labels, milestones = self.configure_github_mock(load_fixture('issues.json')[7:8], load_fixture('labels.json'), [load_fixture('milestone.json')], [[self.fake_comment(self.alice_user, 'Very enhancing.\n\n+enhancement')]])

        self.cappbot.run()

        issues[0].patch.assert_has_calls([call(labels=[u'#new'], milestone=2), call(labels=[u'#new', u'enhancement'])])
        self.assertEquals(issues[0]._mock_comments[-1].body, "**Milestone:** Someday.  **Labels:** #new, enhancement.  **What's next?** A reviewer should examine this issue.")

    def test_multiple_actions_by_comment_label(self):
        issues, labels, milestones = self.configure_github_mock(load_fixture('issues.json')[7:8], load_fixture('labels.json'), [load_fixture('milestone.json')], [[
                self.fake_comment(self.alice_user, 'Very enhancing.\n\n+enhancement\n+#needs-test'),
                self.fake_comment(self.bob_user, '-enhancement\n\n-#needs-test\n+#new\n#acknowledged'),
                self.fake_comment(self.alice_user, "These aren't labels.\n+#hello\n-balloon"),
                self.fake_comment(self.alice_user, "-#acknowledged\n+#needs-test"),
            ]])

        self.cappbot.run()

        issues[0].patch.assert_has_calls([call(labels=[u'#new'], milestone=2), call(labels=[u'#needs-test', u'#new'])])
        self.assertEquals(issues[0]._mock_comments[-1].body, "**Milestone:** Someday.  **Labels:** #needs-test, #new.  **What's next?** A reviewer should examine this issue.")

    def test_action_by_comment_unauthorised(self):
        issues, labels, milestones = self.configure_github_mock(load_fixture('issues.json')[6:7], load_fixture('labels.json'), [load_fixture('milestone.json')], [[self.fake_comment(self.chuck_user, 'I am Chuck and I accept this issue.\n\n+#accepted')]])

        self.cappbot.send_message = Mock()
        self.cappbot.run()

        self.assertTrue(any(u'Ignoring unathorised attempt to alter labels by chuck' in record for record in self.log_handler.formatted_records))

        self.cappbot.send_message.assert_has_calls([])

        issues[0].patch.assert_has_calls([])
        self.assertEquals(issues[0]._mock_comments[-1].body, u"**Labels:** enhancement, question.  **What's next?** A reviewer should examine this issue.")

    def test_action_by_comment_close_issue(self):
        issues, labels, milestones = self.configure_github_mock(load_fixture('issues.json')[7:8], load_fixture('labels.json'), [load_fixture('milestone.json')], [[self.fake_comment(self.alice_user, 'Stupid.\n#wont-fix')]])

        self.cappbot.run()

        issues[0].patch.assert_has_calls([
            call(labels=[u'#new'], milestone=2),
            call(labels=[u'#wont-fix']),
            call(state='closed')
        ])

        self.assertEquals(issues[0]._mock_comments[-1].body, "**Milestone:** Someday.  **Label:** #wont-fix.  **What's next?** A reviewer or core team member has decided against acting upon this issue.")

    def test_action_by_comment_open_issue(self):
        issues, labels, milestones = self.configure_github_mock(load_fixture('issues.json')[7:8], load_fixture('labels.json'), [load_fixture('milestone.json')], [[self.fake_comment(self.alice_user, 'Not actually fixed. \n-#fixed')]])
        issues[0].labels = [labels[6]]
        issues[0].state = 'closed'

        # CappBot will record the issue as manually triaged and ignore any comment actions.
        self.cappbot.run()
        issues[0].patch.assert_has_calls([
            call(labels=[]),
            call(state='open')
        ])

        self.assertEquals(issues[0]._mock_comments[-1].body, "**What's next?** A reviewer should examine this issue.")
