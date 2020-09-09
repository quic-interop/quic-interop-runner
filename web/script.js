(function() {
  // see https://stackoverflow.com/a/43466724/
  function formatTime(seconds) {
    return [
      parseInt(seconds / 60 / 60),
      parseInt(seconds / 60 % 60),
      parseInt(seconds % 60)
    ].join(":").replace(/\b(\d)\b/g, "0$1")
  }

  function getLogLink(log_dir, server, client, testcase, text, type) {
    var a = document.createElement("a");
    a.title = "Logs";
    a.href = "logs/" + log_dir + "/" + server + "_" + client + "/" + testcase;
    a.target = "_blank";
    a.className = "btn btn-xs " + type;
    a.appendChild(document.createTextNode(text));
    return a;
  }

  function getUnsupported(text) {
    var a = document.createElement("a");
    a.className = "btn btn-secondary btn-xs disabled";
    a.appendChild(document.createTextNode(text));
    return a;
  }

  function makeHeaderRow(t, result) {
    var thead = t.createTHead();
    var row = thead.insertRow(0);
    var cell = document.createElement("th");
    row.appendChild(cell);
    cell.scope = "col";
    cell.className = "table-light"
    for(var i = 0; i < result.servers.length; i++) {
      var cell = document.createElement("th");
      row.appendChild(cell);
      cell.scope = "col";
      cell.className = "table-light"
      cell.innerHTML = result.servers[i];
    }
  }

  function makeColumnHeader(tbody, result, i) {
    var row = tbody.insertRow(i);
    var cell = document.createElement("th");
    cell.scope = "row";
    cell.className = "table-light"
    cell.innerHTML = result.clients[i];
    row.appendChild(cell);
    return row;
  }

  function fillInteropTable(result) {
    var t = document.getElementById("interop");
    t.innerHTML = "";
    makeHeaderRow(t, result);
    var tbody = t.createTBody();
    var index = 0;
    for(var i = 0; i < result.clients.length; i++) {
      var row = makeColumnHeader(tbody, result, i);
      for(var j = 0; j < result.servers.length; j++) {
        var cell = row.insertCell(j+1);
        var appendResult = function(el, res, type) {
          result.results[index].forEach(function(item) {
            if(item.result != res) return;
            if(res == "unsupported") {
              el.appendChild(getUnsupported(item.abbr));
            } else {
              el.appendChild(getLogLink(result.log_dir, result.servers[j], result.clients[i], item.name, item.abbr, type))
            }
          });
          cell.appendChild(el);
        }
        var succeeded = document.createElement("span");
        appendResult(succeeded, "succeeded", "btn-success");
        var unsupported = document.createElement("span");
        appendResult(unsupported, "unsupported", "btn-secondary");
        var failed = document.createElement("span");
        appendResult(failed, "failed", "btn-danger");
        index++;
      }
    }
  }

  function fillMeasurementTable(result) {
    var t = document.getElementById("measurements");
    t.innerHTML = "";
    makeHeaderRow(t, result);
    var tbody = t.createTBody();
    var index = 0;
    for(var i = 0; i < result.clients.length; i++) {
      var row = makeColumnHeader(tbody, result, i);
      for(var j = 0; j < result.servers.length; j++) {
        var res = result.measurements[index];
        var cell = row.insertCell(j+1);
        cell.className = "results";
        for(var k = 0; k < res.length; k++) {
          var measurement = res[k];
          var el = document.createElement("div");
          var link = getLogLink(result.log_dir, result.servers[j], result.clients[i], measurement.name, measurement.abbr);
          switch(measurement.result) {
            case "succeeded":
              el.className = "btn btn-xs btn-success";
              el.appendChild(link);
              el.innerHTML += ": " + measurement.details;
              break;
            case "unsupported":
              el.className = "btn btn-xs btn-secondary disabled";
              el.appendChild(getUnsupported(measurement.abbr));
              break;
            case "failed":
              el.className = "btn btn-xs btn-danger";
              el.appendChild(link);
              break;
          }
          cell.appendChild(el);
        }
        index++;
      }
    }
  }

  function dateToString(date) {
    return date.toLocaleDateString("en-US",  { timeZone: 'UTC' }) + " " + date.toLocaleTimeString("en-US", { timeZone: 'UTC', timeZoneName: 'short' });
  }

  function process(result) {
    var startTime = new Date(1000*result.start_time);
    var endTime = new Date(1000*result.end_time);
    var duration = result.end_time - result.start_time;
    document.getElementById("lastrun-start").innerHTML = dateToString(startTime);
    document.getElementById("lastrun-end").innerHTML = dateToString(endTime);
    document.getElementById("duration").innerHTML = formatTime(duration);

    fillInteropTable(result)
    fillMeasurementTable(result)
  }

  function load(dir) {
    document.getElementsByTagName("body")[0].classList.add("loading");
    var xhr = new XMLHttpRequest();
    xhr.responseType = 'json';
    xhr.open('GET', 'logs/' + dir + '/result.json');
    xhr.onreadystatechange = function() {
      if(xhr.readyState !== XMLHttpRequest.DONE) {
        return;
      }
      if(xhr.status != 200) {
        console.log("Received status");
        console.log(xhr.status);
        return;
      }
      process(xhr.response);
      document.getElementsByTagName("body")[0].classList.remove("loading");
    };
    xhr.send();
  }

  load("latest");

  // enable loading of old runs
  var xhr = new XMLHttpRequest();
  xhr.responseType = 'json';
  xhr.open('GET', 'logs/logs.json');
  xhr.onreadystatechange = function() {
    if(xhr.readyState !== XMLHttpRequest.DONE) {
      return;
    }
    if(xhr.status != 200) {
      console.log("Received status");
      console.log(xhr.status);
      return;
    }
    var s = document.createElement("select");
    xhr.response.reverse().forEach(function(el) {
      var opt = document.createElement("option");
      opt.innerHTML = el.replace("logs_", "");
      opt.value = el;
      s.appendChild(opt);
    })
    s.addEventListener("change", function(ev) {
      load(ev.currentTarget.value);
    })
    document.getElementById("available-runs").appendChild(s);
  };
  xhr.send();
})();
