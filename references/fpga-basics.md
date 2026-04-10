# FPGA Verilog/VHDL 基础模板参考

## 工具链

**Xilinx/AMD**：Vivado（2019.2+ 推荐）→ 目标器件 Artix-7 / Zynq  
**Intel/Altera**：Quartus Prime Lite（免费）→ 目标器件 Cyclone IV/V/10  
**开源**：Yosys + nextpnr（iCE40/ECP5 系列）

**仿真工具**：Icarus Verilog（免费）/ ModelSim / Vivado 内置 XSim  
**波形查看**：GTKWave（免费，配合 Icarus）

---

## 设计规范

**三段式状态机**：状态寄存器 + 次态逻辑 + 输出逻辑分开写，不要混在一个 always 块里。  
**时钟域**：所有寄存器只在一个时钟上升沿触发；跨时钟域必须用双 FF 同步器。  
**复位**：统一使用同步复位（`if (!rst_n)`），不混用异步复位。  
**命名**：输入 `i_`，输出 `o_`，寄存器 `r_`，线网 `w_`，常量 `P_`（parameter）。

---

## 基础模块模板

### 标准模块头

```verilog
// module_name.v
// 功能：[简要描述]
// 时钟：clk（上升沿触发）
// 复位：rst_n（低有效，同步复位）

module module_name #(
    parameter P_DATA_WIDTH = 8,
    parameter P_DEPTH      = 16
)(
    input  wire                    clk,
    input  wire                    rst_n,
    // TODO: 添加端口
    input  wire [P_DATA_WIDTH-1:0] i_data,
    output reg  [P_DATA_WIDTH-1:0] o_data
);

// ========================================
// 内部信号声明
// ========================================
reg  [P_DATA_WIDTH-1:0] r_reg;
wire [P_DATA_WIDTH-1:0] w_next;

// ========================================
// 组合逻辑
// ========================================
assign w_next = i_data + 1'b1;  // 示例

// ========================================
// 时序逻辑
// ========================================
always @(posedge clk) begin
    if (!rst_n) begin
        r_reg  <= {P_DATA_WIDTH{1'b0}};
        o_data <= {P_DATA_WIDTH{1'b0}};
    end else begin
        r_reg  <= w_next;
        o_data <= r_reg;
    end
end

endmodule
```

---

## 三段式状态机（UART TX 为例）

```verilog
// uart_tx.v — 8N1 UART 发送器
module uart_tx #(
    parameter P_CLK_FREQ  = 50_000_000,  // 系统时钟 Hz
    parameter P_BAUD_RATE = 115200
)(
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] i_data,      // 要发送的数据
    input  wire       i_valid,     // 数据有效（发送请求）
    output reg        o_tx,        // 串行输出
    output reg        o_busy       // 正在发送中
);

localparam P_BAUD_DIV = P_CLK_FREQ / P_BAUD_RATE - 1;

// ---- 状态定义 ----
localparam [1:0]
    S_IDLE  = 2'd0,
    S_START = 2'd1,
    S_DATA  = 2'd2,
    S_STOP  = 2'd3;

// ---- 寄存器 ----
reg [1:0]  r_state, r_next_state;
reg [15:0] r_baud_cnt;
reg [2:0]  r_bit_cnt;
reg [7:0]  r_data;
wire       w_baud_tick;

assign w_baud_tick = (r_baud_cnt == P_BAUD_DIV);

// ---- 段 1：状态寄存器 ----
always @(posedge clk) begin
    if (!rst_n) r_state <= S_IDLE;
    else        r_state <= r_next_state;
end

// ---- 段 2：次态逻辑 ----
always @(*) begin
    r_next_state = r_state;
    case (r_state)
        S_IDLE:  if (i_valid)                         r_next_state = S_START;
        S_START: if (w_baud_tick)                     r_next_state = S_DATA;
        S_DATA:  if (w_baud_tick && r_bit_cnt == 3'd7) r_next_state = S_STOP;
        S_STOP:  if (w_baud_tick)                     r_next_state = S_IDLE;
    endcase
end

// ---- 段 3：输出逻辑 + 计数器 ----
always @(posedge clk) begin
    if (!rst_n) begin
        o_tx       <= 1'b1;
        o_busy     <= 1'b0;
        r_baud_cnt <= 16'd0;
        r_bit_cnt  <= 3'd0;
        r_data     <= 8'd0;
    end else begin
        // 波特率计数器
        if (r_state == S_IDLE) begin
            r_baud_cnt <= 16'd0;
        end else begin
            r_baud_cnt <= w_baud_tick ? 16'd0 : r_baud_cnt + 1'b1;
        end

        case (r_state)
            S_IDLE: begin
                o_tx   <= 1'b1;
                o_busy <= 1'b0;
                if (i_valid) begin
                    r_data <= i_data;
                    o_busy <= 1'b1;
                end
            end
            S_START: begin
                o_tx <= 1'b0;  // 起始位
            end
            S_DATA: begin
                o_tx <= r_data[r_bit_cnt];
                if (w_baud_tick) r_bit_cnt <= r_bit_cnt + 1'b1;
            end
            S_STOP: begin
                o_tx      <= 1'b1;  // 停止位
                r_bit_cnt <= 3'd0;
            end
        endcase
    end
end

endmodule
```

---

## 同步 FIFO（参数化深度和宽度）

```verilog
// sync_fifo.v
module sync_fifo #(
    parameter P_WIDTH = 8,
    parameter P_DEPTH = 16   // 必须是 2 的幂
)(
    input  wire              clk,
    input  wire              rst_n,
    // 写端口
    input  wire              i_wr_en,
    input  wire [P_WIDTH-1:0] i_wr_data,
    output wire              o_full,
    // 读端口
    input  wire              i_rd_en,
    output reg  [P_WIDTH-1:0] o_rd_data,
    output wire              o_empty,
    // 状态
    output wire [$clog2(P_DEPTH):0] o_count
);

localparam P_ADDR_W = $clog2(P_DEPTH);

reg [P_WIDTH-1:0]   r_mem [0:P_DEPTH-1];
reg [P_ADDR_W:0]    r_wr_ptr, r_rd_ptr;  // 多一位用于满/空判断

wire [P_ADDR_W-1:0] w_wr_addr = r_wr_ptr[P_ADDR_W-1:0];
wire [P_ADDR_W-1:0] w_rd_addr = r_rd_ptr[P_ADDR_W-1:0];

assign o_full  = (r_wr_ptr == {~r_rd_ptr[P_ADDR_W], r_rd_ptr[P_ADDR_W-1:0]});
assign o_empty = (r_wr_ptr == r_rd_ptr);
assign o_count = r_wr_ptr - r_rd_ptr;

always @(posedge clk) begin
    if (!rst_n) begin
        r_wr_ptr <= 0;
        r_rd_ptr <= 0;
    end else begin
        if (i_wr_en && !o_full) begin
            r_mem[w_wr_addr] <= i_wr_data;
            r_wr_ptr <= r_wr_ptr + 1'b1;
        end
        if (i_rd_en && !o_empty) begin
            o_rd_data <= r_mem[w_rd_addr];
            r_rd_ptr  <= r_rd_ptr + 1'b1;
        end
    end
end

endmodule
```

---

## 跨时钟域同步器（双 FF）

```verilog
// cdc_sync.v — 用于单 bit 信号跨时钟域
// WARNING: 仅适用于单比特慢→快跨域；宽总线跨域用握手或异步 FIFO
module cdc_sync #(parameter P_STAGES = 2)(
    input  wire clk_dst,
    input  wire rst_n,
    input  wire i_signal,   // 源时钟域信号
    output wire o_signal    // 目标时钟域同步后信号
);

(* ASYNC_REG = "TRUE" *)  // Vivado 约束：禁止优化这些 FF
reg [P_STAGES-1:0] r_sync;

always @(posedge clk_dst) begin
    if (!rst_n) r_sync <= {P_STAGES{1'b0}};
    else        r_sync <= {r_sync[P_STAGES-2:0], i_signal};
end

assign o_signal = r_sync[P_STAGES-1];

endmodule
```

---

## PWM 发生器（可调频率和占空比）

```verilog
// pwm_gen.v
module pwm_gen #(
    parameter P_CNT_WIDTH = 16
)(
    input  wire                    clk,
    input  wire                    rst_n,
    input  wire [P_CNT_WIDTH-1:0]  i_period,    // 周期（时钟周期数）
    input  wire [P_CNT_WIDTH-1:0]  i_duty,      // 高电平时间（时钟周期数）
    output reg                     o_pwm
);

reg [P_CNT_WIDTH-1:0] r_cnt;

always @(posedge clk) begin
    if (!rst_n) begin
        r_cnt  <= 0;
        o_pwm  <= 1'b0;
    end else begin
        if (r_cnt >= i_period - 1'b1)
            r_cnt <= 0;
        else
            r_cnt <= r_cnt + 1'b1;

        o_pwm <= (r_cnt < i_duty) ? 1'b1 : 1'b0;
    end
end

endmodule
```

---

## 仿真测试台模板（Icarus Verilog）

```verilog
// tb_uart_tx.v
`timescale 1ns/1ps

module tb_uart_tx;

// ---- 参数 ----
parameter CLK_PERIOD = 20;  // 50MHz → 20ns

// ---- 信号 ----
reg        clk, rst_n;
reg  [7:0] data;
reg        valid;
wire       tx, busy;

// ---- 被测模块 ----
uart_tx #(
    .P_CLK_FREQ(50_000_000),
    .P_BAUD_RATE(115200)
) dut (
    .clk(clk), .rst_n(rst_n),
    .i_data(data), .i_valid(valid),
    .o_tx(tx), .o_busy(busy)
);

// ---- 时钟生成 ----
initial clk = 0;
always #(CLK_PERIOD/2) clk = ~clk;

// ---- 测试序列 ----
integer i;
initial begin
    $dumpfile("tb_uart_tx.vcd");  // GTKWave 波形文件
    $dumpvars(0, tb_uart_tx);

    // 复位
    rst_n = 0; valid = 0; data = 0;
    repeat(5) @(posedge clk);
    rst_n = 1;
    repeat(5) @(posedge clk);

    // 发送字符 'H'(0x48)
    data = 8'h48; valid = 1;
    @(posedge clk);
    valid = 0;

    // 等待发送完成
    wait (!busy);
    repeat(10) @(posedge clk);

    // 发送字符串 "ello"
    for (i = 0; i < 4; i = i + 1) begin
        data = "ello"[i];  // NOTE: Verilog 字符串字节顺序
        valid = 1;
        @(posedge clk);
        valid = 0;
        wait (!busy);
    end

    repeat(100) @(posedge clk);
    $display("Simulation complete");
    $finish;
end

// ---- 波形监控 ----
initial begin
    $monitor("t=%0t tx=%b busy=%b", $time, tx, busy);
end

endmodule
```

**运行仿真**：
```bash
iverilog -o sim.out uart_tx.v tb_uart_tx.v
vvp sim.out
gtkwave tb_uart_tx.vcd &
```

---

## Vivado 约束文件模板（XDC）

```tcl
# constraints.xdc — Artix-7（如 Basys3 开发板）

# 系统时钟 100MHz
create_clock -period 10.000 -name sys_clk [get_ports clk]

# I/O 电平标准
set_property IOSTANDARD LVCMOS33 [get_ports {clk rst_n tx rx}]

# 引脚分配（TODO: 根据你的板卡原理图修改）
set_property PACKAGE_PIN W5 [get_ports clk]
set_property PACKAGE_PIN U18 [get_ports rst_n]
set_property PACKAGE_PIN B18 [get_ports tx]
set_property PACKAGE_PIN A18 [get_ports rx]

# 时序例外：跨时钟域路径设为假路径
# set_false_path -from [get_clocks clk_a] -to [get_clocks clk_b]
```

---

## VHDL 等效对照（给需要 VHDL 的用户）

```vhdl
-- 与上面 Verilog 三段式状态机等效的 VHDL 写法
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity uart_tx is
    generic (
        G_CLK_FREQ  : integer := 50_000_000;
        G_BAUD_RATE : integer := 115200
    );
    port (
        clk    : in  std_logic;
        rst_n  : in  std_logic;
        i_data : in  std_logic_vector(7 downto 0);
        i_valid: in  std_logic;
        o_tx   : out std_logic;
        o_busy : out std_logic
    );
end entity;

architecture rtl of uart_tx is
    constant C_BAUD_DIV : integer := G_CLK_FREQ / G_BAUD_RATE - 1;
    type t_state is (S_IDLE, S_START, S_DATA, S_STOP);
    signal r_state   : t_state;
    signal r_baud_cnt: unsigned(15 downto 0);
    signal r_bit_cnt : unsigned(2 downto 0);
    signal r_data    : std_logic_vector(7 downto 0);
    signal w_baud_tick: std_logic;
begin
    w_baud_tick <= '1' when r_baud_cnt = C_BAUD_DIV else '0';

    process(clk)
    begin
        if rising_edge(clk) then
            if rst_n = '0' then
                r_state    <= S_IDLE;
                o_tx       <= '1';
                o_busy     <= '0';
                r_baud_cnt <= (others => '0');
                r_bit_cnt  <= (others => '0');
            else
                -- 波特率计数器
                if r_state = S_IDLE then
                    r_baud_cnt <= (others => '0');
                elsif w_baud_tick = '1' then
                    r_baud_cnt <= (others => '0');
                else
                    r_baud_cnt <= r_baud_cnt + 1;
                end if;

                case r_state is
                    when S_IDLE =>
                        o_tx <= '1'; o_busy <= '0';
                        if i_valid = '1' then
                            r_data <= i_data;
                            o_busy <= '1';
                            r_state <= S_START;
                        end if;
                    when S_START =>
                        o_tx <= '0';
                        if w_baud_tick = '1' then r_state <= S_DATA; end if;
                    when S_DATA =>
                        o_tx <= r_data(to_integer(r_bit_cnt));
                        if w_baud_tick = '1' then
                            if r_bit_cnt = 7 then
                                r_bit_cnt <= (others => '0');
                                r_state <= S_STOP;
                            else
                                r_bit_cnt <= r_bit_cnt + 1;
                            end if;
                        end if;
                    when S_STOP =>
                        o_tx <= '1';
                        if w_baud_tick = '1' then r_state <= S_IDLE; end if;
                end case;
            end if;
        end if;
    end process;
end architecture;
```
