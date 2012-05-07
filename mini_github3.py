#! /usr/bin/env python
# -*- coding: utf8 -*-

#
# BSD License
#
# Copyright (c) 2012, Alexander Ljungberg
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

"""A minimal GitHub API client implemented specifically for the needs of CappBot and not much else (interact with issues, milestons and labels.)

"""

from urllib import quote_plus
from urlparse import urljoin
from link_header import parse_link_value
import argparse
import json
import httplib2


from remoteobjects import RemoteObject, fields, ListObject

# TODO Don't use a global since this only allows one token at a time.
SharedGitHub = None


class GitHubRemoteObject(RemoteObject):
    def get_request(self, headers=None, **kwargs):
        request = super(GitHubRemoteObject, self).get_request(headers=headers, **kwargs)

        # Add authentication header.
        request['headers']['Authorization'] = 'token ' + SharedGitHub.api_token

        return request

    def patch(self, http=None, **kwargs):
        """Remotely alter a previously requested `RemoteObject` through an HTTP ``PATCH`` request.

        """

        location = getattr(self, 'url', None) or getattr(self, '_location', None)
        if location is None:
            raise ValueError('Cannot save %r with no URL to PATCH to' % self)

        body = json.dumps(kwargs)

        headers = {}
        if hasattr(self, '_etag') and self._etag is not None:
            headers['if-match'] = self._etag
        headers['content-type'] = self.content_types[0]

        request = self.get_request(url=location, method='PATCH', body=body, headers=headers)
        if http is None:
            http = httplib2.Http()
        response, content = http.request(**request)

        # print body, response, content

        self.update_from_response(location, response, content)


class GitHubRemoteListObject(ListObject, GitHubRemoteObject):
    def update_from_response(self, url, response, content):
        r = super(GitHubRemoteObject, self).update_from_response(url, response, content)

        # GitHub sends paging information as a response header like this:
        # <https://api.github.com/repos/cappuccino/cappuccino/issues?page=2&state=open>; rel="next", <https://api.github.com/repos/cappuccino/cappuccino/issues?page=11&state=open>; rel="last"
        #
        # <https://api.github.com/repos/cappuccino/cappuccino/issues?page=2&state=closed>; rel="next", <https://api.github.com/repos/cappuccino/cappuccino/issues?page=51&state=closed>; rel="last"

        links = response.get('link')

        self._next_page_url = None
        self._last_page_url = None
        if links:
            links = [parse_link_value(link) for link in links.split(',')]
            for link in links:
                for url, attrs in link.items():
                    if attrs['rel'] == 'next':
                        self._next_page_url = url
                    elif attrs['rel'] == 'last':
                        self._last_page_url = url

        return r


class User(GitHubRemoteObject):
    """A GitHub user account.

    `GET /users/:user`

    {
      "login": "octocat",
      "id": 1,
      "avatar_url": "https://github.com/images/error/octocat_happy.gif",
      "gravatar_id": "somehexcode",
      "url": "https://api.github.com/users/octocat",
      "name": "monalisa octocat",
      "company": "GitHub",
      "blog": "https://github.com/blog",
      "location": "San Francisco",
      "email": "octocat@github.com",
      "hireable": false,
      "bio": "There once was...",
      "public_repos": 2,
      "public_gists": 1,
      "followers": 20,
      "following": 0,
      "html_url": "https://github.com/octocat",
      "created_at": "2008-01-14T04:33:35Z",
      "type": "User"
    }

    """

    login = fields.Field()
    id = fields.Field()
    avatar_url = fields.Field()
    gravatar_id = fields.Field()
    url = fields.Field()
    name = fields.Field()
    company = fields.Field()
    blog = fields.Field()
    location = fields.Field()
    email = fields.Field()
    hireable = fields.Field()
    bio = fields.Field()
    public_repos = fields.Field()
    public_gists = fields.Field()
    followers = fields.Field()
    following = fields.Field()
    html_url = fields.Field()
    created_at = fields.Field()
    type = fields.Field()

    @classmethod
    def get_user(cls, http=None, **kwargs):
        if 'id' in kwargs and kwargs['id'] is not None:
            url = '/users/%s' % quote_plus(kwargs['id'])
        else:
            url = '/user'
        return cls.get(urljoin(SharedGitHub.endpoint, url), http=http)

    def __unicode__(self):
        return u"<User %d>" % self.id


class Label(GitHubRemoteObject):
    """A GitHub label.

    `GET /repos/:user/:repo/labels/:name`

    {
      "url": "https://api.github.com/repos/octocat/Hello-World/labels/bug",
      "name": "bug",
      "color": "f29513"
    }

    """

    url = fields.Field()
    name = fields.Field()
    color = fields.Field()

    def __unicode__(self):
        return u"<Label %s>" % self.name


class Labels(GitHubRemoteListObject):
    entries = fields.List(fields.Object(Label))

    def __getitem__(self, key):
        return self.entries.__getitem__(key)

    @classmethod
    def by_repository(cls, user_name, repo_name, http=None, **kwargs):
        """Get labels by repository.

        `GET /repos/:user/:repo/labels`

        """

        url = '/repos/%s/%s/labels' % (user_name, repo_name)
        return cls.get(urljoin(GitHub.endpoint, url), http=http)

    @classmethod
    def get_or_create_in_repository(cls, user_name, repo_name, label_name, http=None):
        labels = cls.by_repository(user_name, repo_name)
        for label in labels:
            if label.name == label_name:
                return label

        label = Label()
        label.name = label_name
        labels.post(label)

        return label


class Milestone(GitHubRemoteObject):
    """A GitHub milestone.

    `GET /repos/:user/:repo/milestones/:number`

    {
      "url": "https://api.github.com/repos/octocat/Hello-World/milestones/1",
      "number": 1,
      "state": "open",
      "title": "v1.0",
      "description": "",
      "creator": {
        "login": "octocat",
        "id": 1,
        "avatar_url": "https://github.com/images/error/octocat_happy.gif",
        "gravatar_id": "somehexcode",
        "url": "https://api.github.com/users/octocat"
      },
      "open_issues": 4,
      "closed_issues": 8,
      "created_at": "2011-04-10T20:09:31Z",
      "due_on": null
    }

    """

    url = fields.Field()
    number = fields.Field()
    state = fields.Field()
    title = fields.Field()
    description = fields.Field()
    creator = fields.Object(User)
    open_issues = fields.Field()
    closed_issues = fields.Field()
    created_at = fields.Field()
    due_on = fields.Field()

    def __unicode__(self):
        return u"<Milestone %s>" % self.title


class Milestones(GitHubRemoteListObject):
    entries = fields.List(fields.Object(Milestone))

    def __getitem__(self, key):
        return self.entries.__getitem__(key)

    @classmethod
    def by_repository(cls, user_name, repo_name, http=None, **kwargs):
        """Get milestones by repository.

        `GET /repos/:user/:repo/milestones`

        """

        url = '/repos/%s/%s/milestones' % (user_name, repo_name)
        return cls.get(urljoin(GitHub.endpoint, url), http=http)

    @classmethod
    def get_or_create_in_repository(cls, user_name, repo_name, milestone_title, http=None):
        milestones = cls.by_repository(user_name, repo_name)
        for milestone in milestones:
            if milestone.title == milestone_title:
                return milestone

        milestone = Milestone()
        milestone.title = milestone_title
        milestones.post(milestone)

        return milestone


class Comment(GitHubRemoteObject):
    """A GitHub issue comment.

    `GET /repos/:user/:repo/issues/comments/:id`

    {
      "url": "https://api.github.com/repos/octocat/Hello-World/issues/comments/1",
      "body": "Me too",
      "user": {
        "login": "octocat",
        "id": 1,
        "avatar_url": "https://github.com/images/error/octocat_happy.gif",
        "gravatar_id": "somehexcode",
        "url": "https://api.github.com/users/octocat"
      },
      "created_at": "2011-04-14T16:00:49Z",
      "updated_at": "2011-04-14T16:00:49Z"
    }

    """

    id = fields.Field()
    url = fields.Field()
    body = fields.Field()
    user = fields.Object(User)
    created_at = fields.Field()
    updated_at = fields.Field()

    def __unicode__(self):
        return u"<Comment %s>" % self.id


class Comments(GitHubRemoteListObject):
    entries = fields.List(fields.Object(Comment))

    def __getitem__(self, key):
        return self.entries.__getitem__(key)

    @classmethod
    def by_issue(cls, issue, http=None, **kwargs):
        """Get comments by issue.

        `GET /repos/:user/:repo/issues/:number/comments`

        """

        url = '%s/comments' % issue.url
        return cls.get(url, http=http)


class Event(GitHubRemoteObject):
    """A GitHub event.

    `GET /events`

    {
      "type": "Event",
      "public": true,
      "payload": {

      },
      "repo": {
        "id": 3,
        "name": "octocat/Hello-World",
        "url": "https://api.github.com/repos/octocat/Hello-World"
      },
      "actor": {
        "login": "octocat",
        "id": 1,
        "avatar_url": "https://github.com/images/error/octocat_happy.gif",
        "gravatar_id": "somehexcode",
        "url": "https://api.github.com/users/octocat"
      },
      "org": {
        "login": "octocat",
        "id": 1,
        "avatar_url": "https://github.com/images/error/octocat_happy.gif",
        "gravatar_id": "somehexcode",
        "url": "https://api.github.com/users/octocat"
      },
      "created_at": "2011-09-06T17:26:27Z"
    }

    """

    id = fields.Field()
    type = fields.Field()
    public = fields.Field()
    payload = fields.Field()
    repo = fields.Field()
    actor = fields.Object(User)
    org = fields.Object(User)
    created_at = fields.Field()

    def __unicode__(self):
        return u"<Event %s>" % self.id


class Events(GitHubRemoteListObject):
    entries = fields.List(fields.Object(Event))

    def __getitem__(self, key):
        return self.entries.__getitem__(key)

    @classmethod
    def by_repository(cls, repo_user, repo_name, http=None, **kwargs):
        """Get events by repository.

        `GET /repos/:user/:repo/events`

        """

        url = '/repos/%s/%s/events' % (repo_user, repo_name)
        return cls.get(urljoin(GitHub.endpoint, url), http=http)


class Issue(GitHubRemoteObject):
    """A GitHub issue.

    `GET GET /repos/:user/:repo/issues/:number`

    {
      "url": "https://api.github.com/repos/octocat/Hello-World/issues/1",
      "html_url": "https://github.com/octocat/Hello-World/issues/1",
      "number": 1347,
      "state": "open",
      "title": "Found a bug",
      "body": "I'm having a problem with this.",
      "user": {
        "login": "octocat",
        "id": 1,
        "avatar_url": "https://github.com/images/error/octocat_happy.gif",
        "gravatar_id": "somehexcode",
        "url": "https://api.github.com/users/octocat"
      },
      "labels": [
        {
          "url": "https://api.github.com/repos/octocat/Hello-World/labels/bug",
          "name": "bug",
          "color": "f29513"
        }
      ],
      "assignee": {
        "login": "octocat",
        "id": 1,
        "avatar_url": "https://github.com/images/error/octocat_happy.gif",
        "gravatar_id": "somehexcode",
        "url": "https://api.github.com/users/octocat"
      },
      "milestone": {
        "url": "https://api.github.com/repos/octocat/Hello-World/milestones/1",
        "number": 1,
        "state": "open",
        "title": "v1.0",
        "description": "",
        "creator": {
          "login": "octocat",
          "id": 1,
          "avatar_url": "https://github.com/images/error/octocat_happy.gif",
          "gravatar_id": "somehexcode",
          "url": "https://api.github.com/users/octocat"
        },
        "open_issues": 4,
        "closed_issues": 8,
        "created_at": "2011-04-10T20:09:31Z",
        "due_on": null
      },
      "comments": 0,
      "pull_request": {
        "html_url": "https://github.com/octocat/Hello-World/issues/1",
        "diff_url": "https://github.com/octocat/Hello-World/issues/1.diff",
        "patch_url": "https://github.com/octocat/Hello-World/issues/1.patch"
      },
      "closed_at": null,
      "created_at": "2011-04-22T13:33:48Z",
      "updated_at": "2011-04-22T13:33:48Z"
    }

    """

    url = fields.Field()
    html_url = fields.Field()
    number = fields.Field()
    id = fields.Field()
    state = fields.Field()
    title = fields.Field()
    body = fields.Field()
    user = fields.Object(User)
    labels = fields.List(fields.Object(Label))
    assignee = fields.Object(User)
    milestone = fields.Object(Milestone)
    comments = fields.Field()
    pull_request = fields.Field()
    closed_at = fields.Field()
    created_at = fields.Field()
    updated_at = fields.Field()

    def __unicode__(self):
        return u"<Issue %d>" % self.number


class Issues(GitHubRemoteListObject):
    entries = fields.List(fields.Object(Issue))

    @classmethod
    def by_repository(cls, user_name, repo_name, state='open', per_page=30, http=None, **kwargs):
        """Get issues by repository.

        `GET /repos/:user/:repo/issues`

        """

        url = '/repos/%s/%s/issues?state=%s&per_page=%d' % (user_name, repo_name, state, per_page)
        return cls.get(urljoin(GitHub.endpoint, url), http=http)

    @classmethod
    def by_repository_all(cls, user_name, repo_name, per_page=30, http=None):
        """Get all issues by repository (open and closed)."""

        open_issues = cls.by_repository(user_name, repo_name, state='open', per_page=per_page, http=http)
        closed_issues = cls.by_repository(user_name, repo_name, state='closed', per_page=per_page, http=http)

        open_issues.entries.extend(closed_issues.entries)
        return open_issues


class Collaborator(GitHubRemoteObject):
    """A GitHub repo collaborator.

    Not sure if this could just as well be considered a User but it seems
    to have only a subset of the fields.

    `GET /repos/:user/:repo/collaborators/:user`

    {
      "login": "octocat",
      "id": 1,
      "avatar_url": "https://github.com/images/error/octocat_happy.gif",
      "gravatar_id": "somehexcode",
      "url": "https://api.github.com/users/octocat"
    }

    """

    id = fields.Field()
    avatar_url = fields.Field()
    gravatar_id = fields.Field()
    url = fields.Field()
    login = fields.Field()

    def __unicode__(self):
        return u"<Collaborator %s>" % self.id


class Collaborators(GitHubRemoteListObject):
    entries = fields.List(fields.Object(Collaborator))

    @classmethod
    def by_repository(cls, user_name, repo_name, http=None, **kwargs):
        """Get collaborators by repository.

        `GET /repos/:user/:repo/collaborators`

        """

        url = '/repos/%s/%s/collaborators' % (user_name, repo_name)
        return cls.get(urljoin(GitHub.endpoint, url), http=http)


class GitHub(object):
    """An interface to the GitHub API.

    """

    endpoint = 'https://api.github.com/'

    def __init__(self, api_token):
        # TODO Don't use a global.
        global SharedGitHub

        self.api_token = api_token
        SharedGitHub = self

        self.User = User
        self.Event = Event
        self.Events = Events
        self.Issue = Issue
        self.Issues = Issues
        self.Label = Label
        self.Labels = Labels
        self.Milestone = Milestone
        self.Milestones = Milestones
        self.Comment = Comment
        self.Comments = Comments
        self.Collaborator = Collaborator
        self.Collaborators = Collaborators

    def current_user(self, **kwargs):
        return User.get_user(**kwargs)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)

    #parser.add_argument('-u', '--user', required=True,
    #    help="GitHub user for authentication")
    parser.add_argument('-t', '--token', required=True,
        help="GitHub OAuth token for authentication")

    args = parser.parse_args()

    github = GitHub(args.token)

    current_user = github.current_user()
    print u"Authenticated user: %s (%r)" % (current_user.login, current_user.to_dict())

    issues = github.Issues.by_repository("aljungberg", "bottest2")
    for issue in issues:
        print u"Found issue: %s (%s)" % (issue, issue.title)
        for comment in github.Comments.by_issue(issue):
            print u"Comment: %r" % comment.to_dict()

    events = github.Events.by_repository("aljungberg", "bottest2")
    for event in events:
        print u"Event: %s (%s)" % (event, event.to_dict())
