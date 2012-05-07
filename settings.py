## General ##

GITHUB_USER = "cappbot"
GITHUB_TOKEN = ""
GITHUB_REPOSITORY = "cappuccino/cappuccino"

DATABASE = "cappbot-cappuccino-db.json"


## Issue Life Cycle ##

# Defaults to set on new (not yet triaged) issues.
NEW_ISSUE_DEFAULTS = {
    'labels': ['#new'],
    'milestone': 'Someday',
    'assignee': None
}

# When the given label has been set, clear these other labels.
WHEN_LABEL_REMOVE_LABELS = {
    '#acknowledged': [
        '#needs-confirmation',
        '#needs-info',
    ],

    '#accepted': [
        '#needs-confirmation',
        '#needs-info',
        '#needs-review',
    ],

    '#ready-to-commit': [
        '#needs-confirmation',
        '#needs-docs',
        '#needs-improvement',
        '#needs-info',
        '#needs-patch',
        '#needs-reduction',
        '#needs-review',
        '#needs-unit-test',
    ],

    '#fixed': [
        '#needs-confirmation',
        '#needs-docs',
        '#needs-improvement',
        '#needs-info',
        '#needs-patch',
        '#needs-reduction',
        '#needs-review',
        '#needs-unit-test',
        '#ready-to-commit'
    ]
}

# A list of users with permissions to change issues using comment syntax even
# if they are not repository collaborators.
PERMISSIONS = {
    # 'aljungberg': ['labels', 'assignee', 'milestone']
}

## Messages and Paper Trail ##

LABEL_EXPLANATIONS = {
    '#needs-confirmation':  'This issue needs a volunteer to independently reproduce the issue.',
    '#needs-info':          'Additional information should be added as a comment to this isuse.',
    '#needs-review':        'This issue is pending an architectural or implementation design decision and should be discussed or voted on.',
    '#needs-docs':          'Additional documentation patches should be submitted for this issue.',
    '#needs-improvement':   'The code for this issue has problems with formatting or fails a capp_lint check, has bugs, or has non-optimal logic or algorithms. It should be improved upon.',
    '#needs-patch':         'This issue needs a volunteer to write and submit code to address it.',
    '#needs-reduction':     'A minimal test app should be created which demonstrates the concern of this issue in isolation.',
    '#needs-unit-test':     'This issue needs a volunteer to write and submit one or more unit tests execercising the changes and/or the relevant parts of the original problem.',
    '#duplicate':           'This issue duplicates another existing issue. Refer to the original issue for further information.',
    '#fixed':               'This issue is considered successfully resolved.',
    '#wont-fix':            'A reviewer or core team member has decided against acting upon this issue.',
    '#works-for-me':        'Attempts to reproduce the problem described by this issue has failed to reveal any erroneous situation.',
    '#new':                 'A reviewer should examine this issue.',
    '#accepted':            'This issue has been confirmed but needs further review.',
}

# If any of these labels are set, their explanation is the only one given.
FINAL_WORD_LABELS = ('#fixed', '#duplicate', '#wont-fix', '#works-for-me')


def getPaperTrailMessage(assignee, milestone, labels, votes=None):
    """Produce the paper trail message.

    >>> getPaperTrailMessage(None, None, set(['#new',]))
    "**Label:** #new.  **What's next?** A reviewer should examine this issue."
    >>> getPaperTrailMessage(None, '1.0', set(['feature', '#ready-to-commit',]))
    "**Milestone:** 1.0.  **Labels:** #ready-to-commit, feature.  **What's next?** The changes for this issue are ready to be committed by a member of the core team."
    >>> getPaperTrailMessage('aljungberg', None, set(['feature', '#ready-to-commit',]))
    "**Assignee:** [aljungberg](https://github.com/aljungberg).  **Labels:** #ready-to-commit, feature.  **What's next?** The changes for this issue are ready to be committed by [aljungberg](https://github.com/aljungberg)."
    >>> getPaperTrailMessage(None, None, set(['bug', '#acknowledged', '#needs-patch',]))
    "**Labels:** #acknowledged, #needs-patch, bug.  **What's next?** \\n\\n * This issue needs a volunteer to write and submit code to address it."
    >>> getPaperTrailMessage(None, None, set(['bug', '#acknowledged', '#needs-patch',]))
    "**Labels:** #acknowledged, #needs-patch, bug.  **What's next?** \\n\\n * This issue needs a volunteer to write and submit code to address it."
    >>> getPaperTrailMessage(None, 'Someday', set(['#acknowledged', '#someday']), 3)
    "**Milestone:** Someday.  **Votes:** 3.  **Labels:** #acknowledged, #someday.  **What's next?** A reviewer should examine this issue."

    """

    r = ""

    if assignee:
        r = "**Assignee:** %s.  " % ("[%s](https://github.com/%s)" % (assignee, assignee) if assignee else "-")
    if milestone:
        r += "**Milestone:** %s.  " % (milestone or "-")

    if votes is not None:
        r += "**Vote%s:** %d.  " % ('s' if votes != 1 else '', votes)

    if labels:
        r += "**Label%s:** %s.  " % ('s' if len(labels) != 1 else '', ", ".join(sorted(labels)) if labels else "-")

    next = getWhatsNextMessage(assignee, milestone, labels)
    if next:
        r += '''**What's next?** %s''' % next

    if not r:
        r = 'This issue has not been labeled.'

    return r.strip()


def getWhatsNextMessage(assignee, milestone, labels):
    who = "[%s](https://github.com/%s)" % (assignee, assignee) if assignee else None
    for final_label in FINAL_WORD_LABELS:
        if final_label in labels:
            return LABEL_EXPLANATIONS[final_label]
    if '#ready-to-commit' in labels:
        return "The changes for this issue are ready to be committed by %s." % (who or "a member of the core team")
    needs = [label for label in labels if label.startswith('#needs') and label in LABEL_EXPLANATIONS]
    if needs:
        return '\n\n * %s' % ('\n * '.join(LABEL_EXPLANATIONS[label] for label in needs))

    return "A reviewer should examine this issue."
