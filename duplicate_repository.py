"""Duplicate a github repository's issues, milestones and labels.

NOTE: You must run this twice.
* first time, no flags
* second time, the update flag to update the issues state and comments

Usage:
  duplicate_repository.py -u USER -p PASS -s SOURCE -d DEST [--update]
  duplicate_repository.py --version

Options:
  -h --help                  show this help message and exit
  --version                  show version and exit
  -v --verbose               print status messages
  --update                   update existing issues
  -u USER --username=USER    github username to use
  -p PASS --password=PASS    github password to use
  -s SOURCE --source=SOURCE  source repository to copy from
  -d DEST --destination=DEST destination repository to copy to

"""

import base64
import json
import urllib2

from docopt import docopt
from utils import parse_link_value

SERVER = 'api.github.com'


class Config(object):
  def __init__(self, arguments):
    for k, v in arguments.items():
      arg = k.strip('-')
      setattr(self, arg, v)

    self.src_url = 'https://%s/repos/%s' % (SERVER, self.source)
    self.dest_url = 'https://%s/repos/%s' % (SERVER, self.destination)
    self.basic_auth = 'Basic ' + base64.urlsafe_b64encode(
      '%s:%s' % (self.username, self.password))


# Store the config instance here.
config = None


def authed_request(url, data=None, do_open=True):
  '''Open an authenticated request to a given GitHub URL.'''
  request = urllib2.Request(
      '%s/milestones?state=open' % url,
      json.dumps(data) if data else None,
      headers={'Authorization': config.basic_auth}
  )
  request.add_header('Content-Type', 'application/json')
  request.add_header('Accept', 'application/json')
  if do_open:
    response = urllib2.urlopen(request)
    return {
      'data': json.loads(response.read()),
      'response': response,
      'request': request,
    }
  return request


def get_milestones(url):
  milestones = []
  urls = ('%s/milestones?state=open' % url,
          '%s/milestones?state=closed' % url)
  for u in urls:
    try:
      milestones += authed_request(u)['data']
    except urllib2.HTTPError as e:
      if '404' in str(e):
        continue
      raise e
  return milestones


def get_labels(url):
  return authed_request('%s/labels?state=open' % url)['data']


def get_issues_by_state(url, state):
  next_page = '%s/issues?sort=created&direction=asc&state=%s' % (url, state)
  issues = []
  while next_page:
    dict_res = authed_request(next_page)
    issues += dict_res['data']
    next_page = dict_res['response'].headers.get('Link')
    if next_page:
      next_pages = [parse_link_value(page) for page in next_page.split(',')]
      next_page = [page.keys()[0] for page in next_pages if page[page.keys()[0]]['rel'] == 'next']
      if next_page:
        next_page = next_page[0]
  return issues


def get_issues(url):
  issues = get_issues_by_state(url, 'closed') + get_issues_by_state(url, 'open')
  return sorted(issues, key=lambda i: i['number'])


def get_comments_on_issue(issue):
  if issue.get('comments'):
    try:
      comments = authed_request('%s/comments?state=%s&sort=created&direction=asc' % (issue['url'], issue['state']))['data']
    except Exception as e:
      print e
      print issue
      return []
    return comments
  else:
    return []


def import_milestones(milestones):
  for source in milestones:
    try:
      m = authed_request('%s/milestones' % config.dest_url, {
        'title': source['title'],
        'state': source['state'],
        'description': source['description'],
        'due_on': source['due_on'],
      })['data']
      print 'Successfully created milestone %s' % m['title']
    except urllib2.HTTPError:
      pass


def import_labels(labels, existing_labels):
  existing_label_names = [l['name'] for l in existing_labels]
  for source in labels:
    if source['name'] in existing_label_names:
      continue

    res_label = authed_request('%s/labels' % config.dst_url, {
      'name': source['name'],
      'color': source['color']
    })['data']
    print 'Successfully created label %s' % res_label['name']


def import_issues(issues, existing_issues, dst_milestones, dst_labels):
  existing_issue_numbers = [issue['number'] for issue in existing_issues]
  for source in issues:
    if source['number'] in existing_issue_numbers and not source.get('comments'):
      print 'Skipping issue number %d.' % source['number']
      continue
    labels = []
    if 'labels' in source:
      for src_label in source['labels']:
        name = src_label['name']
        labels.append(name)

    milestone = None
    if 'milestone' in source and source['milestone'] is not None:
      title = source['milestone']['title']
      for dst_milestone in dst_milestones:
        if dst_milestone['title'] == title:
          milestone = dst_milestone['number']
          break

    assignee = None
    if 'assignee' in source and source['assignee'] is not None:
      assignee = source['assignee']['login']

    body = None
    if 'body' in source and source['body'] is not None:
      body = source['body']

    res_issue = authed_request('%s/issues' % config.dst_url, {
      'title': source['title'],
      'body': body,
      'assignee': assignee,
      'milestone': milestone,
      'labels': labels
    })['data']
    print 'Successfully created issue %s' % res_issue['title']


def update_issues(issues, existing_issues):
  for source, dest in zip(issues, existing_issues):
    comments = get_comments_on_issue(source)
    existing_comments = get_comments_on_issue(dest)
    if existing_comments:
      existing_comments_bodies = [c['body'] for c in existing_comments]
    else:
      existing_comments_bodies = []
    if comments:
      for comment in comments:
        if comment['body'] in existing_comments_bodies:
          continue
        authed_request('%s/comments' % dest['url'], {
          'body': comment['body'],
        })

    if dest['state'] != source['state']:
      req = authed_request(dest['url'], {
        'state': source['state'],
      }, do_open=False)
      req.get_method = lambda: 'PATCH'
      urllib2.urlopen(req)


def main(arguments):
  global config
  config = Config(arguments)

  if config.update:
    # update issues to add comments and issue state
    issues = get_issues(config.src_url)
    existing_issues = get_issues(config.dest_url)
    update_issues(issues, existing_issues)
  else:
    # get milestones and labels
    milestones = get_milestones(config.src_url)
    labels = get_labels(config.dest_url)

    # import milestones and labels, skipping existing labels
    import_milestones(milestones)
    existing_labels = get_labels(config.dest_url)
    import_labels(labels, existing_labels)

    # get imported milestones and labels
    milestones = get_milestones(config.dest_url)
    labels = get_labels(config.dest_url)

    # create issues
    issues = get_issues(config.src_url)
    existing_issues = get_issues(config.dest_url)
    import_issues(issues, existing_issues, milestones, labels)


if __name__ == '__main__':
  arguments = docopt.docopt(__doc__, version='0.1')
  main(arguments)
