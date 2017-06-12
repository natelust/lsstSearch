#!/usr/bin/env python
import sys,os
location = '/Users/nate/Dropbox/workspace/LSSTSearch'
sys.path.append(location)
from LSSTSearch import *
import cgi,cgitb
cgitb.enable() #for debugging
print("Content-Type: text/html")    
print("\n")                             
 
print('<html>')
javaScript = '''<script>
function goBack() {
    window.history.back();
    }
    </script>'''
print('<head><title>LSSTSearch Results</title>')
print(javaScript)
print('</head>')
print('<body>')
if sys.version_info[0] < 3:
    data_uri = open(os.path.join(location,'images/MEDLogoBLK.jpg'),'rb').read().encode('base64').replace('\n','')
else:
    import base64
    data_uri =base64.b64encode(open(os.path.join(location,'images/MEDLogoBLK.jpg'),'rb').read())
#img_tag = '<img width="400" src="data:image/png;base64,{}">'.format(data_uri)
#print(img_tag)
print('<h1>Search Results</h1>')
print('<h2>Previous Page</h2><button onclick="goBack()">Go Back</button>')
form = cgi.FieldStorage()
name = form.getvalue('fname')
fieldType = form.getvalue('fieldType')
webSearch(name,fieldType)
print('</body></html>')

