config = "";
all = [];
var table = "";

var protocol = 'ws:';
if (window.location.protocol == 'https:') {
  protocol = 'wss:';
  }
var host = "" + protocol + "//" + window.location.hostname + ":" + window.location.port;
var ws_status = new WebSocket(host+"/status");
var ws_config = new WebSocket(host+"/config");

ws_status.onmessage = function(e) {
  x = JSON.parse(e.data);
  if (x.pidstats) {
    x.pidstats["datetime"]=unix_to_yymmdd_hhmmss(x.pidstats.time);
    x.pidstats.err = x.pidstats.err*-1;
    x.pidstats.out = x.pidstats.out*100;
    x.pidstats.catching_up = x.catching_up
    if (x.catching_up == true) {
      x.pidstats.catchingup = x.pidstats.ispoint;
      }
    all.push(x.pidstats);
    }
  var str = JSON.stringify(x, null, 2);
  document.getElementById("state").innerHTML = "<pre>"+str+"</pre>"
  table.replaceData(latest(20));
  drawall(all);

  document.getElementById("error-current").innerHTML = rnd(x.pidstats.err);
  document.getElementById("error-1min").innerHTML = rnd(average("err",1,all));
  document.getElementById("error-5min").innerHTML = rnd(average("err",5,all));
  document.getElementById("error-15min").innerHTML = rnd(average("err",15,all));
  
  document.getElementById("temp").innerHTML = rnd(x.pidstats.ispoint);
  document.getElementById("target").innerHTML = rnd(x.pidstats.setpoint);

  document.getElementById("heat-pct").innerHTML = rnd(x.pidstats.out);

  document.getElementById("catching-up").innerHTML = rnd(percent_catching_up(all));
  };

ws_config.onopen = function() {
  ws_config.send('GET');
  };

ws_config.onmessage = function(e) {
  config = JSON.parse(e.data);
  //console.log(e);
  };

create_table(all);

//---------------------------------------------------------------------------
function rnd(number) {
return Number(number).toFixed(2);
}
//---------------------------------------------------------------------------
function average(field,minutes,data) {
if(data[0]!=null) {
  var t = data[data.length - 1].time;
  var oldest = t-(60*minutes);
  var q = "SELECT AVG("+ field + ") from ? where time>=" + oldest.toString();
  var avg = alasql(q,[data]);
  return avg[0]["AVG(err)"];
  }
return 0;
}

//---------------------------------------------------------------------------
function drawall(data) {
draw_temps(data);
draw_error(data);
draw_heat(data);
draw_p(data);
draw_i(data);
draw_d(data);
}

//---------------------------------------------------------------------------
function draw_heat(data) {
var traces=[];
var rows = alasql('SELECT datetime, out from ?',[data]);
var title = 'Heating Percent';

var trace = {
    x: unpack(rows, 'datetime'),
    y: unpack(rows, 'out'),
    name: 'heat',
    mode: 'lines',
    line: { color: 'rgb(255,0,0)', width:2 }
    };

traces.push(trace);

spot = document.getElementById('heat');
var layout = {
  title: title,
  showlegend: true,
  };
Plotly.newPlot(spot, traces, layout, {displayModeBar: false});
}

//---------------------------------------------------------------------------
function draw_p(data) {
var traces=[];
var rows = alasql('SELECT datetime, p from ?',[data]);
var title = 'Proportional';

var trace = {
    x: unpack(rows, 'datetime'),
    y: unpack(rows, 'p'),
    name: 'p',
    mode: 'lines',
    line: { color: 'rgb(0,0,255)', width:2 }
    };

traces.push(trace);

spot = document.getElementById('p');
var layout = {
  title: title,
  showlegend: true,
  };
Plotly.newPlot(spot, traces, layout, {displayModeBar: false});
}

//---------------------------------------------------------------------------
function draw_i(data) {
var traces=[];
var rows = alasql('SELECT datetime, i from ?',[data]);
var title = 'Integral';

var trace = {
    x: unpack(rows, 'datetime'),
    y: unpack(rows, 'i'),
    name: 'i',
    mode: 'lines',
    line: { color: 'rgb(0,0,255)', width:2 }
    };

traces.push(trace);

spot = document.getElementById('i');
var layout = {
  title: title,
  showlegend: true,
  };
Plotly.newPlot(spot, traces, layout, {displayModeBar: false});
}

//---------------------------------------------------------------------------
function draw_d(data) {
var traces=[];
var rows = alasql('SELECT datetime, d from ?',[data]);
var title = 'Derivative';

var trace = {
    x: unpack(rows, 'datetime'),
    y: unpack(rows, 'd'),
    name: 'd',
    mode: 'lines',
    line: { color: 'rgb(0,0,255)', width:2 }
    };

traces.push(trace);

spot = document.getElementById('d');
var layout = {
  title: title,
  showlegend: true,
  };
Plotly.newPlot(spot, traces, layout, {displayModeBar: false});
}


//---------------------------------------------------------------------------
function draw_error(data) {
var traces=[];
var rows = alasql('SELECT datetime, err from ?',[data]);
var title = 'Error';

var trace = {
    x: unpack(rows, 'datetime'),
    y: unpack(rows, 'err'),
    name: 'error',
    mode: 'lines',
    line: { color: 'rgb(255,0,0)', width:2 }
    };

traces.push(trace);

spot = document.getElementById('error');
var layout = {
  title: title,
  showlegend: true,
  //xaxis : { tickformat:'%b' },
  };
Plotly.newPlot(spot, traces, layout, {displayModeBar: false});
}

//---------------------------------------------------------------------------
function draw_temps(data) {
var traces=[];
var rows = alasql('SELECT datetime, ispoint, setpoint, catchingup from ?',[data]);
var title = 'Temperature and Target';

var trace = {
    x: unpack(rows, 'datetime'),
    y: unpack(rows, 'setpoint'),
    name: 'target',
    mode: 'lines',
    line: { color: 'rgb(0,0,255)', width:2 }
    };

traces.push(trace);

trace = {
    x: unpack(rows, 'datetime'),
    y: unpack(rows, 'ispoint'),
    name: 'temp',
    mode: 'lines',
    line: { color: 'rgb(255,0,0)', width:2 }
    };

traces.push(trace);

trace = {
    x: unpack(rows, 'datetime'),
    y: unpack(rows, 'catchingup'),
    name: 'catchup',
    mode: 'markers',
    marker: { color: 'rgb(0,255,0)', width:3 }
    };

traces.push(trace);

spot = document.getElementById('temps');
var layout = {
  title: title,
  showlegend: true,
  //xaxis : { tickformat:'%b' },
  };
Plotly.newPlot(spot, traces, layout, {displayModeBar: false});
}

//---------------------------------------------------------------------------
function unpack(rows, key) {
  return rows.map(function(row) { return row[key]; });
}


//---------------------------------------------------------------------------
function unix_to_yymmdd_hhmmss(t) {
var date = new Date(t * 1000);
var newd = new Date(date.getTime() - date.getTimezoneOffset()*60000);
//return date.toLocaleString('en-US',{hour12:false}).replace(',','');
return newd.toISOString().replace("T"," ").substring(0, 19);
}
//---------------------------------------------------------------------------
function latest(n) {
//sql = "select * from ? order by time desc limit " + n;
sql = "select * from ? order by time desc";
results = alasql(sql,[all]);
return results;
}

//---------------------------------------------------------------------------
function percent_catching_up(data) {
var sql = "select sum(timeDelta) as slip from ? where catching_up=true";
var a = alasql(sql,[data]);
a = a[0]["slip"];
sql = "select sum(timeDelta) as [all] from ?";
var b = alasql(sql,[data]);
b = b[0]["all"];
return a/b*100;
}
//---------------------------------------------------------------------------
function create_table(data) {
table = new Tabulator("#state-table", {
  height:300,
  data:data, //assign data to table
  //layout:"fitColumns", //fit columns to width of table (optional)
  columns:[
    {title:"DateTime", field:"datetime"},
    {title:"Target", field:"setpoint"},
    {title:"Temp", field:"ispoint"},
    {title:"Error", field:"err"},
    {title:"P", field:"p"},
    {title:"I", field:"i"},
    {title:"D", field:"d"},
    {title:"Heat", field:"out"},
    {title:"Catching Up", field:"catching_up"},
    {title:"Time Delta", field:"timeDelta"},
    ]});
}

//---------------------------------------------------------------------------
function csv_string() {
table.download("csv", "kiln-state.csv");
}

