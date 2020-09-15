/* globals document, window, console, URLSearchParams, XMLHttpRequest, $, history */

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
    $(a).attr("data-toggle", "tooltip").attr("data-placement", "bottom").tooltip();
    a.href = "logs/" + log_dir + "/" + server + "_" + client + "/" + testcase;
    a.target = "_blank";
    a.className = "btn btn-xs " + type + " testcase-" + text.toLowerCase();
    a.appendChild(document.createTextNode(text));
    return a;
  }

  function getUnsupported(text) {
    var a = document.createElement("a");
    a.className = "btn btn-secondary btn-xs disabled testcase-" + text.toLowerCase();
    a.appendChild(document.createTextNode(text));
    return a;
  }

  function makeColumnHeaders(t, result) {
    var thead = t.createTHead();
    var row = thead.insertRow(0);
    var cell = document.createElement("th");
    row.appendChild(cell);
    cell.scope = "col";
    cell.className = "table-light client-any";
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
    var cell = document.createElement("th");
    cell.scope = "row";
    cell.className = "table-light client-" + result.clients[i];
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
          link.className = "measurement btn btn-xs ";
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
      if (tooltip) {
        b.title = tooltip;
        $(b).attr("data-toggle", "tooltip").attr("data-placement", "bottom").tooltip();
      }
      b.type = "button";
      b.className = type + " btn btn-light";
      return b;
  }

  function setButtonState() {
    var params = new URLSearchParams(history.state ? history.state.path : window.location.search);
    var show = {};
    Object.keys(map).forEach(type => {
      map[type] = params.getAll(type).map(x => x.toLowerCase().split(",")).flat();
      if (map[type].length === 0)
        map[type] = $("#" + type + " :button").get().map(x => x.innerText.toLowerCase());
      $("#" + type + " :button").removeClass("active font-weight-bold").addClass("text-muted font-weight-light").filter((i, e) => map[type].includes(e.innerText.toLowerCase())).addClass("active font-weight-bold").removeClass("text-muted font-weight-light");
      show[type] = map[type].map(e => "." + type + "-" + e);
    });

    $(".result td").add(".result th").add(".result td a").hide();

    const show_classes = show.client.map(el1 => show.server.map(el2 => el1 + el2)).flat().join();
    $(".client-any," + show_classes).show();

    $(".result " + show.client.map(e => "th" + e).join()).show();
    $(".result " + show.server.map(e => "th" + e).join()).show();
    $(".measurement," + show.testcase.join()).show();
  }

  function clickButton(e) {
    function toggle(array, value) {
        var index = array.indexOf(value);
        if (index === -1)
            array.push(value);
         else
            array.splice(index, 1);
    }

    e.target.blur();
    const type = [...e.target.classList].filter(x => Object.keys(map).includes(x))[0];
    const which = e.target.innerText.toLowerCase();

    var q = [];
    var params = new URLSearchParams(history.state ? history.state.path : window.location.search);
    if (params.has(type) && params.get(type))
      q = params.get(type).split(",");
    else {
      q = map[type];
      params.delete(type);
    }
    toggle(q, which);

    if (q.length === $("#" + type + " :button").length)
      params.delete(type);
    else
      params.set(type, q);

    var refresh = window.location.protocol + "//" + window.location.host + window.location.pathname + "?" + decodeURIComponent(params.toString());
    window.history.pushState(null, null, refresh);
    toggle(map[type], which);
    setButtonState();
  }


  function process(result) {
    var startTime = new Date(1000*result.start_time);
    var endTime = new Date(1000*result.end_time);
    var duration = result.end_time - result.start_time;
    document.getElementById("lastrun-start").innerHTML = dateToString(startTime);
    document.getElementById("lastrun-end").innerHTML = dateToString(endTime);
    document.getElementById("duration").innerHTML = formatTime(duration);
    document.getElementById("quic-vers").innerHTML =
      "<tt>" + result.quic_version + "</tt> (\"draft-" + result.quic_draft + "\")";

    fillInteropTable(result);
    fillMeasurementTable(result);

    $("#client").add("#server").add("#testcase").empty();
    $("#client").append(result.clients.map(e => makeButton("client", e))).click(clickButton);
    $("#server").append(result.servers.map(e => makeButton("server", e))).click(clickButton);
    const tcases = result.results.flat().map(x => [x.abbr, x.name]).filter((e, i, a) => a.map(x => x[0]).indexOf(e[0]) === i);
    if (result.hasOwnProperty("tests")) {
      const tdesc = Object.fromEntries(result.tests.map(x => [x.abbr, x.desc]));
      $("#testcase").append(tcases.map(e => makeButton("testcase", e[0], tdesc[e[0]]))).click(clickButton);
    } else {
      // TODO: this else can eventually be removed, when all past runs have the test descriptions in the json
      $("#testcase").append(tcases.map(e => makeButton("testcase", e[0], ""))).click(clickButton);
    }
    setButtonState();
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
