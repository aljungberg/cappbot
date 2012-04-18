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
