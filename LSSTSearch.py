import os
import whoosh
from whoosh.qparser import QueryParser
import argparse
import sys
import re
import datetime
try:
    import git
except:
    print('This tool requires gitpython to be installed')
    sys.exit()

if 'LSSTSearchPath' in os.environ and \
        os.path.isdir(os.environ['LSSTSearchPath']):
    homepath = os.environ['LSSTSearchPath']
else:
    homepath = os.path.join(os.path.expanduser("~"), ".LSSTSearch")

schema = whoosh.fields.Schema(
        path=whoosh.fields.NGRAMWORDS(minsize=3, maxsize=15, stored=True),
        content=whoosh.fields.TEXT(phrase=True, stored=True),
        branch=whoosh.fields.NGRAMWORDS(minsize=3, maxsize=15, stored=True),
        commitTime=whoosh.fields.STORED,
        repository=whoosh.fields.NGRAMWORDS(minsize=3, maxsize=15,
                                            stored=True),
        sha=whoosh.fields.ID(stored=True),
        unique=whoosh.fields.ID(unique=True),
        log=whoosh.fields.TEXT(phrase=True, stored=True))
gitUrl = ''


def hasgit(string):
    if string.count('.git') > 0:
        return True
    else:
        return False


def makeUnicode(obj):
    if sys.version_info[0] > 2:
        return str(obj)
    if type(obj) == str:
        obj = unicode(obj, 'utf-8', errors='ignore')
    return obj


def addFile(writer, blob, branch, commitTime, repo, sha):
    try:
        content = blob.data_stream.read()
        content = makeUnicode(content)
        blobPath = makeUnicode(blob.path)
        branch = makeUnicode(branch)
        repo = makeUnicode(repo)
        sha = makeUnicode(sha)
        unique = blobPath+repo+branch
        writer.update_document(path=blobPath, content=content,
                               branch=branch, commitTime=commitTime,
                               repository=repo, sha=sha, unique=unique)
    except Exception as e:
        print(e)
        sys.exit(1)


def addLog(writer, branch, commitTime, repo, sha, log):
    try:
        branch = makeUnicode(branch)
        repo = makeUnicode(repo)
        sha = makeUnicode(sha)
        log = makeUnicode(log)
        unique = repo+branch
        writer.update_document(branch=branch, repository=repo, sha=sha,
                               log=log, unique=unique)
    except Exception as e:
        print(e)
        sys.exit(1)


def checkHome():
    if not os.path.exists(homepath):
        os.mkdir(homepath)
        # git.Repo.clone_from(gitUrl, homepath)


def getIndex(name, schema=None, indexname=None):
    if whoosh.index.exists_in(homepath, indexname=indexname):
        return whoosh.index.open_dir(homepath, indexname=indexname)
    else:
        return whoosh.index.create_in(homepath, schema=schema,
                                      indexname=indexname)


def indexer(directory, checkhome=True, basePath=''):
    try:
        import magic
    except:
        print('This functionality requires python-magic to be installed')
        sys.exit()

    def istext(buff):
        text = magic.from_buffer(buff.read(1024), mime=True)
        return re.search(r'.*text', text)is not None
    try:
        import git
    except:
        print('gitpython must be installed on the system')
        sys.exit()

    print(directory)
    ix = getIndex(homepath, schema=schema, indexname=directory)
    fullDirectory = os.path.join(basePath, directory)
    try:
        repo = git.Repo(fullDirectory)
    except:
        print('Directory does not appear to be a git repository, skipping')
        print(fullDirectory)
        return
    try:
        len(repo.remotes.origin.refs)
    except:
        print('Directory does not have an origin set')
        return
    if checkhome:
        # Note this is the function checkHome not the variable
        checkHome()
    writer = ix.writer(limitmb=400, procs=2)
    stem_ana = writer.schema["content"].analyzer
    stem_ana.cachesize = -1
    stem_ana.clean()
    # This is the reference time, which is 6 months old
    timeReference = (datetime.datetime.now() - datetime.timedelta(days=180) -
                     datetime.datetime(1970, 1, 1)).total_seconds()
    with ix.searcher() as searcher:
        # Fetch all the values in the stored fields so we can check for
        # updating of documents
        allStoredFields = list(searcher.all_stored_fields())
        # Loop over each of the remote branches
        allPaths = []
        allBranches = []
        for field in allStoredFields:
            try:
                allPaths.append(field['path'])
                allBranches.append(field['branch'])
            except:
                pass
        total = len(repo.remotes.origin.refs)
        # Create a variable to track if adding a file needs done
        doAdd = False
        for i, remote in enumerate(repo.remotes.origin.refs):
            lastCommit = remote.commit.committed_date
            if lastCommit > timeReference:
                # The log is pulled so that it can be stored as a
                # searchable document
                remotelog = repo.git.log(remote.name)
                branchName = remote.name.replace('origin/', '')
                # Add the log as a searchable document, makesure to set
                # content to None
                repoSha = remote.commit.hexsha
                addLog(writer, branchName, lastCommit,
                       directory, repoSha, remotelog)
                print(str(i)+':'+str(total))
                # In a given branch, loop over each of the files
                for item in remote.commit.tree.list_traverse():
                    # check if the file is already in the index and up to date
                    if item.path not in allPaths or\
                            branchName not in allBranches:
                        if istext(item.data_stream):
                            doAdd = True
                    else:
                        # check if the document is up to date
                        docField = searcher.document(path=item.path,
                                                     branch=branchName)
                        # The first if statement handles if the index was some
                        # how corrupt
                        if docField is None:
                            if istext(item.data_stream):
                                doAdd = True
                        elif docField['commitTime'] == lastCommit and \
                                docField['commitTime'] > timeReference:
                                pass
                        # the stored record is older than last commit,
                        # update
                        elif docField['commitTime'] < lastCommit and \
                                docField['CommitTime'] > timeReference:
                            if istext(item.data_stream):
                                doAdd = True
                        else:
                            # Delete the document if it is old and stale
                            docNumber = searcher.document(path=item.path,
                                                          branch=branchName)
                            writer.delete_by_document(docNumber)
                    if doAdd:
                        # Add a document if the conditions are met
                        sha = item.hexsha
                        addFile(writer, item, branchName, lastCommit,
                                directory, sha)
                        doAdd = False
    writer.commit()


def searcher(string, fieldType='content'):
    string = makeUnicode(string)
    repos = os.listdir(homepath)
    repos = [m.group(1) for m in
             [re.match('_([^_].*)_\d*[.]toc', l) for l in repos] if m]
    ixList = [getIndex(homepath, schema=schema, indexname=r) for r in repos]
    searchers = [ix.searcher() for ix in ixList]
    parser = QueryParser(fieldType, schema)
    parser.add_plugin(whoosh.qparser.FuzzyTermPlugin())
    query = parser.parse(string)
    totalResults = []
    for entry in searchers:
        results = entry.search(query, terms=True, limit=100)
        totalResults.append(results)
    return totalResults


def webSearch(string, fieldType='content'):
    resultsList = searcher(string, fieldType)
    moreLikeThis = []
    for results in resultsList:
        if not results.is_empty():
            results.fragmenter = \
                    whoosh.highlight.PinpointFragmenter(maxchars=400,
                                                        surround=150)
            for entry, score in results.key_terms(fieldType):
                moreLikeThis.append(entry)
            for hit in results:
                print('<br>')
                print('<hr>')
                if fieldType == 'content':
                    outString = 'Path: '+hit['path']+' Repository: '\
                        + hit['repository']+", Branch: "+hit['branch']+' '
                    outString += '<a href="https://github.com/lsst/' + \
                        hit['repository']+'/blob/'+hit['branch']+'/' + \
                        hit['path']+'" target="_blank">Github Link</a><br>'
                    print(outString)
                if fieldType == 'log':
                    print('Repository: '+hit['repository']+", Branch:"
                          + hit['branch'])
                print('<br>')
                print('<pre>')
                outstring = hit.highlights(fieldType, top=10).replace("\\n", "<br />")
                print(outstring)
                print('</pre>')
                print('<br>')

    print('<h2>More Like This</h2>')
    print('<hr>')
    for entry in moreLikeThis:
        newtext = entry
        for stub in string.split():
            if ':' in stub:
                newtext = newtext+' '+stub
        # print('<br>')
        print('<form name="pyform" method="POST" '
              'action="/cgi-bin/webserver.py">')
        print('<input type="hidden" name="fname" value="'+newtext+'"/>')
        print('<input type="hidden" name="fieldType" value="'+fieldType+'"/>')
        print('<input type="submit" name="submit" value="'+entry+'" />')
        print('</form>')


def commandLineSearch(string):
    if not isinstance(string, list):
        string = [string]
    resultsList = searcher(string[0])
    for results in resultsList:
        if not results.is_empty():
            results.fragmenter = \
                whoosh.highlight.PinpointFragmenter(maxchars=400, surround=150)
            results.formatter = whoosh.highlight.UppercaseFormatter()
            for hit in results:
                # print(hit.fields())
                print ('\n~~~\n')
                print('Path: '+hit['path']+', Repository: '
                      + hit['repository']+", Branch: " + hit['branch'] + '\n')
                print(hit.highlights("content", top=10).replace("\\n", "\n"))


def metaIndexer(superDirectory):
    checkHome()
    dirs = os.listdir(superDirectory)
    for d in dirs:
        if os.path.isdir(os.path.join(superDirectory, d)) and not\
                d.startswith('.'):
            indexer(d, checkhome=False, basePath=superDirectory)


def gitPull():
    return
    repo = git.Repo(homepath)
    repo.remotes.origin.fetch()
    commitsBehind = repo.iter_commits('master..origin/master')
    count = sum(1 for c in commitsBehind)
    if count > 0:
        print('Updating search index')
        repo.remotes.origin.pull()
    else:
        print('Search index is already up to date')


def gitPush():
    return
    repo = git.Repo(homepath)
    try:
        repo.remotes.origin.push()
    except:
        print('There was an error pushing the search index')


def updater(extra):
    parser = argparse.ArgumentParser()
    parser.add_argument('updateAction', help='Actions to control the'
                        "updator: download (pulls update from git) update dir "
                        "(updates the index of just one dir) metaUpdate dir "
                        "(updates the index with subdirectories of dir, one "
                        "for every repo) gitUpdate (pushes anupdated index to "
                        "git)")
    args2, extra2 = parser.parse_known_args(extra)
    if args2.updateAction == 'download':
        gitPull()
    elif args2.updateAction == 'update':
        if extra2 and os.path.isdir(extra2[0]):
            base, directory = os.path.split(extra2[0])
            indexer(directory, basePath=base)
        else:
            print('Please supply a valid directory')
    elif args2.updateAction == 'metaUpdate':
        if extra2 and os.path.isdir(extra2[0]):
            metaIndexer(extra2[0])
        else:
            print('Please supply a valid directory')
    elif args2.updateAction == 'gitUpdate':
        gitPush()
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", help='Base action, either update,'
                        'search,gui')
    args, extra = parser.parse_known_args()
    if args.action == 'update':
        updater(extra)
    elif args.action == 'search':
        commandLineSearch(extra)
    elif args.action == 'gui':
        print('operation not implimented yet')
    else:
        parser.print_help()
        sys.exit(0)
