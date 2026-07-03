// CONFIGURE THESE
var GITHUB_TOKEN = "YOUR_TOKEN_HERE"
var GITHUB_OWNER = "reubenchuaa"
var GITHUB_REPO  = "amanda-health-ai"
var FILE_PATH    = "health/data.json"

var API_URL = "https://api.github.com/repos/" + GITHUB_OWNER + "/" + GITHUB_REPO + "/contents/" + FILE_PATH

var headers = {
  "Authorization": "token " + GITHUB_TOKEN,
  "Accept": "application/vnd.github.v3+json",
  "Content-Type": "application/json",
  "User-Agent": "Scriptable"
}

var input = args.shortcutParameter
if (!input) {
  console.log("No input - run via a Shortcut")
  Script.complete()
} else {

var today = new Date().toISOString().split("T")[0]
var newEntry = typeof input === "string" ? JSON.parse(input) : input
newEntry.date = today

var getReq = new Request(API_URL)
getReq.headers = headers
var fileInfo = await getReq.loadJSON()
var sha = fileInfo.sha
var decoded = Data.fromBase64String(fileInfo.content.replace(/\n/g, "")).toRawString()
var existing = JSON.parse(decoded)

var daily = existing.daily || []
var idx = -1
for (var i = 0; i < daily.length; i++) {
  if (daily[i].date === today) { idx = i; break }
}
if (idx >= 0) {
  var merged = {}
  var keys1 = Object.keys(daily[idx])
  for (var k = 0; k < keys1.length; k++) { merged[keys1[k]] = daily[idx][keys1[k]] }
  var keys2 = Object.keys(newEntry)
  for (var k = 0; k < keys2.length; k++) { merged[keys2[k]] = newEntry[keys2[k]] }
  daily[idx] = merged
} else {
  daily.push(newEntry)
}
existing.daily = daily
existing.synced_at = new Date().toISOString()

var content = Data.fromString(JSON.stringify(existing, null, 2)).toBase64String()

var putReq = new Request(API_URL)
putReq.method = "PUT"
putReq.headers = headers
putReq.body = JSON.stringify({
  message: "sync: " + today,
  content: content,
  sha: sha
})
var result = await putReq.loadJSON()

if (result.content) {
  console.log("Synced successfully")
  Script.setShortcutOutput("success")
} else {
  console.log("Error: " + JSON.stringify(result))
  Script.setShortcutOutput("failed")
}

Script.complete()
}
