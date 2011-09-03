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

Create 'tracking issues' for each pull request in a GitHub repo so that the pull request can be triaged, labeled and assigned through its tracking issue. Since the tracking issue will be the focal point of discussion on the pull request, any discussion in the pull request is also moved over to the tracking issue.
"""

# TODO
# In the future, CappBot can be extended to support issue triaging in general:
# * add '#to-review' labels to new issues
# * echo label, assignment and milestone changes in the comments to leave a proper paper trail with dates
# * move issues still open to future milestones when an existing milestone is closed ('left-over' issues)
# * close dead issues (e.g. issue has #needs-patch label but no patch has been added in 6 months)

from github2.client import Github
from logbook.compat import RedirectLoggingHandler
import argparse
import logbook
import logging
import re

class CappBot(object):
  PULL_TRACKING_LABEL = "Pull Request"
  REVIEW_LABEL = "#to-review"
  ISSUE_DEFAULT_LABELS = [REVIEW_LABEL]

  # Receives the pull request the issue will be for as the first formatting argument.
  ISSUE_TITLE_FORMAT = "[Pull request #{0.number:d}] {0.title}"
  ISSUE_COMMENT_FORMAT = "This issue tracks pull request #{0.number:d}: {0.body}."
  ISSUE_PULL_CLOSED_FORMAT = "Pull request #{0.number:d} has been closed. ~~~ CappBot"
  ISSUE_PULL_REOPENED_FORMAT = "Pull request #{0.number:d} has been reopened. ~~~ CappBot"
  # {0} is source comment
  ISSUE_MOVED_COMMENT_FORMAT = "*[Pull request comment by [{0.user}](https://github.com/{0.user}) at {0.created_at}]:*\n{0.body}\n *~~~~ CappBot*"
  # If this is ever changed, the new regex needs to be backwards compatible with the first format,
  # or duplicates will result.
  ISSUE_MOVED_COMMENT_REGEX = r'^\*\[Pull request comment by (.*?) at (.*?)\]:\*\n(.*?)\n \*~~~~ CappBot\*$'

  # Receives the new issue request as the first formatting argument.
  PULL_REQUEST_COMMENT_FORMAT = "Issue #{0.number:d} has been created to track this pull request. ~~~ CappBot"
  # If this is ever changed, the new regex needs to be backwards compatible with the first format,
  # or duplicates will result.
  PULL_REQUEST_COMMENT_REGEX = r'^Issue #(\d+) has been created to track this pull request\. ~~~ CappBot$'
  PULL_REQUEST_DONT_SYNC_COMMENT_KEYWORD = '#cappbot-ignore'

  def __init__(self, repo_name, user, token):
    self.github = Github(username=user, api_token=token, requests_per_second=100)
    self.repo_name = repo_name
    self.username = user

  def create_issue(self, title, body):
    issue = self.github.issues.open(self.repo_name, title, body)
    logbook.info("Created issue %d: %s." % (issue.number, title))
    return issue

  def create_comment(self, issue, body):
    comment = self.github.issues.comment(self.repo_name, issue.number, body)
    # comment = None
    logbook.info("Commented on issue #%d: %s" % (issue.number, body))
    return comment

  def get_issue_number_for_pull(self, pull_request):
    for comment in self.github.issues.comments(self.repo_name, pull_request.number):
      if not comment.user == self.username:
        continue

      m = re.match(self.PULL_REQUEST_COMMENT_REGEX, comment.body)
      if not m:
        continue

      return int(m.group(1))

  def sync_comments(self, source, dest):
    source_comments = list(self.github.issues.comments(self.repo_name, source.number))
    dest_comments = list(self.github.issues.comments(self.repo_name, dest.number))

    # Copy over all comments which haven't already been copied over. Unfortunately we can't
    # insert comments anywhere but at the end, so the comment stream might get out of order
    # if people comment faster than CappBot moves things.
    for source_comment in source_comments:
      # Don't copy over CappBot's own comments.
      if source_comment.user == self.username:
        continue

      # Ignore comments containing an ignore tag.
      if self.PULL_REQUEST_DONT_SYNC_COMMENT_KEYWORD in source_comment.body:
        continue

      # Only copy comments over once.
      for dest_comment in dest_comments:
        # We're only looking for comments cappbot made.
        if dest_comment.user != self.username:
          continue

        m = re.match(self.ISSUE_MOVED_COMMENT_REGEX, dest_comment.body)
        print m.groups()
        if m and source_comment.user in m.group(1) and m.group(3) == source_comment.body:
          logbook.debug("Not copying source comment '%s' because this looks familiar: '%s'." % (source_comment.body, dest_comment.body))
          break
      else:
        # No match.
        formatted_comment = self.ISSUE_MOVED_COMMENT_FORMAT.format(source_comment, dest, source_comment)
        self.create_comment(dest, formatted_comment)

  def run(self):
    github = self.github
    repo_name = self.repo_name

    pull_requests = github.pull_requests.list(repo_name, state='open') + github.pull_requests.list(repo_name, state='closed')
    logbook.info("Found %d pull request(s)." % len(pull_requests))

    # Filter out pull requests we have already dealt with.
    # pull_requests = [request for request in pull_requests if request.discussion]

    # Make sure each pull request has a proper issue.
    for pull_request in pull_requests:
      issue_number = self.get_issue_number_for_pull(pull_request)
      if issue_number is not None:
        issue = self.github.issues.show(self.repo_name, issue_number)

        if not issue:
          logbook.warn("The tracking issue for pull request #%d is gone. Skipping." % pull_request.number)
          continue
      else:
        issue = self.create_issue(title=self.ISSUE_TITLE_FORMAT.format(pull_request), body=self.ISSUE_COMMENT_FORMAT.format(pull_request))
        self.create_comment(pull_request, self.PULL_REQUEST_COMMENT_FORMAT.format(issue))
        for label in self.ISSUE_DEFAULT_LABELS:
          self.github.issues.add_label(repo_name, issue.number, label)

      # Add this flag whether the issue or new, or an old issue on which the flag somehow disappeared.
      self.github.issues.add_label(repo_name, issue.number, self.PULL_TRACKING_LABEL)

      # Now we have the tracking issue for the pull request (possibly newly created).
      self.sync_comments(pull_request, issue)

      # If the pull request is closed, the tracking issue can be closed.
      # Do this last so that any final comments have been synced before the issue is closed.
      if pull_request.state == 'closed' and issue.state == 'open':
        self.create_comment(issue, self.ISSUE_PULL_CLOSED_FORMAT.format(pull_request, issue))
        self.github.issues.close(repo_name, issue.number)
      elif pull_request.state == 'open' and issue.state == 'closed':
        # The pull request has been reopened (or someone closed the issue without closing the pull request.)
        self.create_comment(issue, self.ISSUE_PULL_REOPENED_FORMAT.format(pull_request, issue))
        self.github.issues.reopen(repo_name, issue.number)

if __name__ == '__main__':
  github_logger = logging.getLogger('github2.request')
  github_logger.addHandler(RedirectLoggingHandler())

  parser = argparse.ArgumentParser(description=__doc__)

  parser.add_argument('repository',
                      help='GitHub repository to work with, e.g. cappuccino/cappuccino')
  parser.add_argument('--username', default='cappbot',
                      help='GitHub username to use')
  parser.add_argument('--api-token-path', default='secret_api_token.txt',
                      help='the path to a file containing the GitHub API token to use')

  args = parser.parse_args()

  with open(args.api_token_path, "rb") as f:
    github_token = f.read().strip()
  if not github_token:
    raise Exception("unable to load API token")

  CappBot(args.repository, args.username, github_token).run()
