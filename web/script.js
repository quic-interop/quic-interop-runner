(function() {
  // see https://stackoverflow.com/a/43466724/
  function formatTime(seconds) {
    return [
      parseInt(seconds / 60 / 60),
      parseInt(seconds / 60 % 60),
      parseInt(seconds % 60)
    ].join(":").replace(/\b(\d)\b/g, "0$1")
  }

  function getLogLink(log_dir, server, client, testcase, text) {
    if(log_dir.length == 0) log_dir = "logs"; // backwards-compatibility mode
    var a = document.createElement("a");
    a.title = "Logs";
    a.href = log_dir + "/" + server + "_" + client + "/" + testcase;
    a.target = "_blank";
    a.appendChild(document.createTextNode(text));
    return a;
  }

  function getUnsupported(text) {
    var a = document.createElement("a");
    a.appendChild(document.createTextNode(text));
    return a;
  }

  function fillInteropTable(result) {
    var t = document.getElementById("interop");
    t.innerHTML = "";
    var row = t.insertRow(0);
    row.insertCell(0);
    for(var i = 0; i < result.servers.length; i++) {
      row.insertCell(i+1).innerHTML = result.servers[i];
    }
    var index = 0;
    for(var i = 0; i < result.clients.length; i++) {
      var row = t.insertRow(i+1);
      row.insertCell(0).innerHTML = result.clients[i];
      for(var j = 0; j < result.servers.length; j++) {
        var cell = row.insertCell(j+1);
        var appendResult = function(el, res) {
          result.results[index].forEach(function(item) {
            if(item.result != res) return;
            if(res == "unsupported") {
              el.appendChild(getUnsupported(item.abbr));
            } else {
              el.appendChild(getLogLink(result.log_dir, result.servers[j], result.clients[i], item.name, item.abbr))
            }
          });
          cell.appendChild(el);
        }
        cell.className = "results";
        var succeeded = document.createElement("div");
        succeeded.className = "text-success";
        appendResult(succeeded, "succeeded");
        var unsupported = document.createElement("div");
        unsupported.className = "text-secondary";
        appendResult(unsupported, "unsupported");
        var failed = document.createElement("div");
        failed.className = "text-danger";
        appendResult(failed, "failed");
        index++;
      }
    }
  }

  function fillMeasurementTable(result) {
    var t = document.getElementById("measurements");
    t.innerHTML = "";
    var row = t.insertRow(0);
    row.insertCell(0);
    for(var i = 0; i < result.servers.length; i++) {
      row.insertCell(i+1).innerHTML = result.servers[i];
    }
    var index = 0;
    for(var i = 0; i < result.clients.length; i++) {
      var row = t.insertRow(i+1);
      row.insertCell(0).innerHTML = result.clients[i];
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
              el.className = "text-success";
              el.appendChild(link);
              el.innerHTML += ": " + measurement.details;
              break;
            case "unsupported":
              el.className = "text-secondary";
              el.appendChild(getUnsupported(measurement.abbr));
              break;
            case "failed":
              el.className = "text-danger";
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
    var estNextEndTime = new Date(1000*(result.end_time + duration));
    document.getElementById("lastrun-start").innerHTML = dateToString(startTime);
    document.getElementById("lastrun-end").innerHTML = dateToString(endTime);
    document.getElementById("duration").innerHTML = formatTime(duration);
    document.getElementById("est-next-end").innerHTML = dateToString(estNextEndTime);

    fillInteropTable(result)
    fillMeasurementTable(result)
  }

  function load(dir) {
    var xhr = new XMLHttpRequest();
    xhr.responseType = 'json';
    xhr.open('GET', dir + '/result.json');
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
    };
    xhr.send();
  }

  load("latest");

  // enable loading of old runs
  var xhr = new XMLHttpRequest();
  xhr.responseType = 'json';
  xhr.open('GET', 'logs.json');
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
      opt.innerHTML = el.substr(5);
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
