
#ifndef PROXY_MODEL_H
#define PROXY_MODEL_H

// This file was auto-generated using m2cgen and scikit-learn
// Model: RandomForestClassifier (n_estimators=3, max_depth=3)
// Features: [dwell_time_ms, inter_scan_time_ms]

class ProxyModel {
public:
  static int predict(float dwell_time_ms, float inter_scan_time_ms) {
    double input[2] = {(double)dwell_time_ms, (double)inter_scan_time_ms};
    double output[2];
    score(input, output);
    return output[1] > 0.5 ? 1 : 0;
  }

private:
  static void score(double *input, double *output);
};

#include <string.h>
void add_vectors(double *v1, double *v2, int size, double *result) {
  for (int i = 0; i < size; ++i)
    result[i] = v1[i] + v2[i];
}
void mul_vector_number(double *v1, double num, int size, double *result) {
  for (int i = 0; i < size; ++i)
    result[i] = v1[i] * num;
}
void ProxyModel::score(double *input, double *output) {
  double var0[2];
  double var1[2];
  double var2[2];
  double var3[2];
  if (input[1] <= 3064.2884521484375) {
    memcpy(var3, (double[]){0.0, 1.0}, 2 * sizeof(double));
  } else {
    memcpy(var3, (double[]){1.0, 0.0}, 2 * sizeof(double));
  }
  double var4[2];
  if (input[0] <= 1498.9573364257812) {
    if (input[0] <= 1158.6868286132812) {
      if (input[0] <= 1112.5047607421875) {
        memcpy(var4, (double[]){0.26706827309236947, 0.7329317269076305},
               2 * sizeof(double));
      } else {
        memcpy(var4, (double[]){0.7692307692307693, 0.23076923076923078},
               2 * sizeof(double));
      }
    } else {
      if (input[0] <= 1442.2649536132812) {
        memcpy(var4, (double[]){0.12030075187969924, 0.8796992481203008},
               2 * sizeof(double));
      } else {
        memcpy(var4, (double[]){0.3333333333333333, 0.6666666666666666},
               2 * sizeof(double));
      }
    }
  } else {
    memcpy(var4, (double[]){1.0, 0.0}, 2 * sizeof(double));
  }
  add_vectors(var3, var4, 2, var2);
  double var5[2];
  if (input[0] <= 1504.3499755859375) {
    if (input[1] <= 3218.25) {
      memcpy(var5, (double[]){0.0, 1.0}, 2 * sizeof(double));
    } else {
      memcpy(var5, (double[]){1.0, 0.0}, 2 * sizeof(double));
    }
  } else {
    memcpy(var5, (double[]){1.0, 0.0}, 2 * sizeof(double));
  }
  add_vectors(var2, var5, 2, var1);
  mul_vector_number(var1, 0.3333333333333333, 2, var0);
  memcpy(output, var0, 2 * sizeof(double));
}

#endif
