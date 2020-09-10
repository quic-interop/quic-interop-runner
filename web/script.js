/* globals document, window, console, URLSearchParams, XMLHttpRequest, $ */

(function() {
  "use strict";
  const map = { client: {}, server: {}, testcase: {} };

  // see https://stackoverflow.com/a/43466724/
  function formatTime(seconds) {
    return [
      parseInt(seconds / 60 / 60),
      parseInt(seconds / 60 % 60),
      parseInt(seconds % 60)
    ].join(":").replace(/\b(\d)\b/g, "0$1");
  }

  function getLogLink(log_dir, server, client, testcase, text, type) {
    var a = document.createElement("a");
    a.title = "Logs";
    a.href = "logs/" + log_dir + "/" + server + "_" + client + "/" + testcase;
    a.target = "_blank";
    a.className = "btn btn-xs " + type + " testcase-" + text.toLowerCase();
    a.appendChild(document.createTextNode(text));
    return a;
  }

  function getUnsupported(text) {
    var a = document.createElement("a");
    a.className = "btn btn-secondary btn-xs disabled" + text + " testcase-" + text.toLowerCase();
    a.appendChild(document.createTextNode(text));
    return a;
  }

  function makeColumnHeaders(t, result) {
    var thead = t.createTHead();
    var row = thead.insertRow(0);
    var cell = document.createElement("th");
    row.appendChild(cell);
    cell.scope = "col";
    cell.className = "table-light";
    for(var i = 0; i < result.servers.length; i++) {
      cell = document.createElement("th");
      row.appendChild(cell);
      cell.scope = "col";
      cell.className = "table-light server-" + result.servers[i];
      cell.innerHTML = result.servers[i];
    }
  }

  function makeRowHeader(tbody, result, i) {
    var row = tbody.insertRow(i);
    row.className = "client-" + result.clients[i];
    var cell = document.createElement("th");
    cell.scope = "row";
    cell.className = "table-light";
    cell.innerHTML = result.clients[i];
    row.appendChild(cell);
    return row;
  }

  function fillInteropTable(result) {
    var index = 0;
    var appendResult = function(el, res, type, i, j) {
      result.results[index].forEach(function(item) {
        if(item.result !== res) return;
        if(res === "unsupported")
          el.appendChild(getUnsupported(item.abbr));
        else
          el.appendChild(getLogLink(result.log_dir, result.servers[j], result.clients[i], item.name, item.abbr, type));
      });
    };

    var t = document.getElementById("interop");
    t.innerHTML = "";
    makeColumnHeaders(t, result);
    var tbody = t.createTBody();
    for(var i = 0; i < result.clients.length; i++) {
      var row = makeRowHeader(tbody, result, i);
      for(var j = 0; j < result.servers.length; j++) {
        var cell = row.insertCell(j+1);
        cell.className = "server-" + result.servers[j] + " client-" + result.clients[i];
        appendResult(cell, "succeeded", "btn-success", i, j);
        appendResult(cell, "unsupported", "btn-secondary", i, j);
        appendResult(cell, "failed", "btn-danger", i, j);
        index++;
      }
    }
  }

  function fillMeasurementTable(result) {
    var t = document.getElementById("measurements");
    t.innerHTML = "";
    makeColumnHeaders(t, result);
    var tbody = t.createTBody();
    var index = 0;
    for(var i = 0; i < result.clients.length; i++) {
      var row = makeRowHeader(tbody, result, i);
      for(var j = 0; j < result.servers.length; j++) {
        var res = result.measurements[index];
        var cell = row.insertCell(j+1);
        cell.className = "server-" + result.servers[j] + " client-" + result.clients[i];
        for(var k = 0; k < res.length; k++) {
          var measurement = res[k];
          var link = getLogLink(result.log_dir, result.servers[j], result.clients[i], measurement.name, measurement.abbr);
          link.className = "btn btn-xs ";
          switch(measurement.result) {
            case "succeeded":
              link.className += " btn-success";
              link.innerHTML += ": " + measurement.details;
              break;
            case "unsupported":
              link.className += " btn-secondary disabled";
              link.appendChild(getUnsupported(measurement.abbr));
              break;
            case "failed":
              link.className += " btn-danger";
              break;
          }
          cell.appendChild(link);
        }
        index++;
      }
    }
  }

  function dateToString(date) {
    return date.toLocaleDateString("en-US",  { timeZone: 'UTC' }) + " " + date.toLocaleTimeString("en-US", { timeZone: 'UTC', timeZoneName: 'short' });
  }

  function makeButton(type, text, tooltip) {
      var b = document.createElement("button");
      b.innerHTML = text;
      if (tooltip) b.title = tooltip;
      b.type = "button";
      b.className = type + " btn btn-light";
      return b;
  }

  function setButtonState(type) {
    var params = new URLSearchParams(window.location.search);
    map[type] = params.getAll(type).map(x => x.toLowerCase().split(",")).flat();
    if (map[type].length === 0)
      map[type] = $("#" + type + " :button").get().map(x => x.innerText.toLowerCase());
    $("#" + type + " :button").filter((i, e) => map[type].includes(e.innerText.toLowerCase())).toggleClass("active");

    $(".result td").add(".result th").add(".result tr").add(".result td a").filter((i, e) => {
      var cand = [...e.classList].filter(x => x.startsWith(type + "-"))[0];
      if (cand === undefined) return false;
      cand = cand.replace(type + "-", "");
      return map[type].includes(cand) === false;
    }).hide();
  }

  function clickButton(e) {
    function toggle(array, value) {
        var index = array.indexOf(value);
        if (index === -1)
            array.push(value);
         else
            array.splice(index, 1);
    }

    const type = [...e.target.classList].filter(x => Object.keys(map).includes(x))[0];
    const which = e.target.innerText.toLowerCase();

    var q;
    var params = new URLSearchParams(window.location.search.toLowerCase);
    if (params.has(type))
      q = params.get(type).split(",");
    else
      q = map[type];
    toggle(q, which);
    params.set(type, q);
    window.location.search = decodeURIComponent(params.toString());
    toggle(map[type], which);
  }


  function process(result) {
    var startTime = new Date(1000*result.start_time);
    var endTime = new Date(1000*result.end_time);
    var duration = result.end_time - result.start_time;
    document.getElementById("lastrun-start").innerHTML = dateToString(startTime);
    document.getElementById("lastrun-end").innerHTML = dateToString(endTime);
    document.getElementById("duration").innerHTML = formatTime(duration);

    fillInteropTable(result);
    fillMeasurementTable(result);

    $("#client").add("#server").add("#testcase").empty();
    $("#client").append(result.clients.map(e => makeButton("client", e))).click(clickButton);
    setButtonState("client");

    $("#server").append(result.servers.map(e => makeButton("server", e))).click(clickButton);
    setButtonState("server");

    const tcases = result.results.flat().map(x => [x.abbr, x.name]).filter((e, i, a) => a.map(x => x[0]).indexOf(e[0]) === i);
    $("#testcase").append(tcases.map(e => makeButton("testcase", e[0], e[1]))).click(clickButton);
    setButtonState("testcase");
  }

  function load(dir) {
    document.getElementsByTagName("body")[0].classList.add("loading");
    var xhr = new XMLHttpRequest();
    xhr.responseType = 'json';
    xhr.open('GET', 'logs/' + dir + '/result.json');
    xhr.onreadystatechange = function() {
      if(xhr.readyState !== XMLHttpRequest.DONE) return;
      if(xhr.status !== 200) {
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
    if(xhr.readyState !== XMLHttpRequest.DONE) return;
    if(xhr.status !== 200) {
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
    });
    s.addEventListener("change", function(ev) {
      load(ev.currentTarget.value);
    });
    document.getElementById("available-runs").appendChild(s);
  };
  xhr.send();
})();
